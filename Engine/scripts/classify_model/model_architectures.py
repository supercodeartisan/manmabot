"""Model architecture definitions for the classifier.

All models implement the ``BaseClassifierModel`` interface and are created
through ``ModelFactory`` so the training pipeline is model-agnostic.

To add a new architecture:
    1. Implement a class inheriting ``BaseClassifierModel``.
    2. Register it: ``@ModelFactory.register("your_name")``.
    3. Select it from ``Config(architecture="your_name")``.

Registered names:
    "resnet18"             single head, ``forward`` -> logits
    "resnet18_multihead"   v1 two heads: main category + detail level band
    "resnet18_twohead_v2"  v2 two heads: 5 fixed main categories + fine identity

Reserved future names: "efficientnet".

The ResNet18 models are split into a feature extractor (``ResNet18Backbone``,
outputs a 512-dim vector) and swappable heads. Future heads can be attached to
the same backbone without retraining it.
"""
from abc import ABC, abstractmethod
from typing import Optional, Tuple

import torch
import torch.nn as nn
from torchvision.models import resnet18, ResNet18_Weights


class BaseClassifierModel(nn.Module, ABC):
    """Common interface every classification model must implement.

    - Every model is an ``nn.Module``: ``forward()``, ``state_dict()``
      saving/loading, and training work directly on it.
    - Every model is constructed by ``ModelFactory.create`` with a
      ``(num_classes, **kwargs)`` signature and exposes ``get_model()``.
    """

    @abstractmethod
    def get_model(self) -> nn.Module:
        ...


class ResNet18Backbone(nn.Module):
    """ResNet18 feature extractor (conv1..layer4 + global avg pooling).

    ``forward`` returns a flattened ``out_features``-dim feature vector
    (512 for ResNet18) with no classification head attached.

    ``pretrained=True`` downloads ImageNet weights (training init).
    ``pretrained=False`` builds randomly initialized layers — use this when
    loading a full checkpoint so inference never hits torch.hub / stdout.
    """

    def __init__(self, pretrained: bool = True):
        super().__init__()
        weights = ResNet18_Weights.DEFAULT if pretrained else None
        base = resnet18(weights=weights)
        self.conv1 = base.conv1
        self.bn1 = base.bn1
        self.relu = base.relu
        self.maxpool = base.maxpool
        self.layer1 = base.layer1
        self.layer2 = base.layer2
        self.layer3 = base.layer3
        self.layer4 = base.layer4
        self.avgpool = base.avgpool
        self.out_features = base.fc.in_features

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)
        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)
        x = self.avgpool(x)
        return torch.flatten(x, 1)


class ClassificationHead(nn.Module):
    """Classification head: dropout, then a linear projection to ``class_num``.

    Dropout is active only in ``train()``; ``eval()`` is a pass-through so live
    inference is unchanged. Dropout has no learned weights, so old checkpoints
    still load.
    """

    def __init__(self, in_features: int, class_num: int, dropout_p: float = 0.3):
        super().__init__()
        self.dropout = nn.Dropout(dropout_p)
        self.fc = nn.Linear(in_features, class_num)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.fc(self.dropout(features))


class MainHead(ClassificationHead):
    """Main-category head.

    v1 used whatever coarse folders the dataset had. v2 locks this to the five
    combat categories BACKGROUND, ITEM, MONSTER, NPC, PLAYER (WINDOW is gone).
    """


class DetailHead(ClassificationHead):
    """Detail-category head (fine labels: Orc, Skeleton, Dragon, specific NPC/item types)."""


class FineHead(nn.Module):
    """Fine-identity head with one hidden bottleneck layer.

    ``DetailHead`` is a single linear layer, which is enough for a handful of
    classes but thin for ~60 monster species where several pairs differ only
    by colour (돌 골렘 13급 vs 라바 골렘 43급). A hidden layer lets the head
    combine backbone features per species instead of resting on one linear
    boundary each. ``hidden=0`` degrades to the plain linear head.
    """

    def __init__(
        self,
        in_features: int,
        class_num: int,
        hidden: int = 256,
        dropout_p: float = 0.3,
    ):
        super().__init__()
        if hidden and hidden > 0:
            self.body = nn.Sequential(
                nn.Dropout(dropout_p),
                nn.Linear(in_features, hidden),
                nn.BatchNorm1d(hidden),
                nn.ReLU(inplace=True),
                nn.Dropout(dropout_p),
            )
            self.fc = nn.Linear(hidden, class_num)
        else:
            self.body = nn.Dropout(dropout_p)
            self.fc = nn.Linear(in_features, class_num)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.fc(self.body(features))


class ResNet18Model(BaseClassifierModel):
    """ResNet18 backbone + linear classification head."""

    def __init__(
        self,
        class_num: int,
        freeze_backbone: bool = True,
        dropout_p: float = 0.3,
        pretrained: bool = True,
    ):
        super().__init__()
        self.backbone = ResNet18Backbone(pretrained=pretrained)
        self.head = ClassificationHead(
            self.backbone.out_features, class_num, dropout_p=dropout_p
        )
        if freeze_backbone:
            for param in self.backbone.parameters():
                param.requires_grad = False
            for param in self.head.parameters():
                param.requires_grad = True

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.backbone(x))

    def get_model(self) -> nn.Module:
        return self


class ResNet18MultiHeadModel(BaseClassifierModel):
    """ResNet18 backbone shared by two independent classification heads.

    Both heads consume the same 512-dim feature vector produced by the
    backbone. ``forward`` returns ``(main_output, detail_output)``.
    """

    def __init__(
        self,
        class_num: int,
        detail_class_num: int,
        freeze_backbone: bool = True,
        dropout_p: float = 0.3,
        pretrained: bool = True,
    ):
        super().__init__()
        self.backbone = ResNet18Backbone(pretrained=pretrained)
        self.main_head = MainHead(
            self.backbone.out_features, class_num, dropout_p=dropout_p
        )
        self.detail_head = DetailHead(
            self.backbone.out_features, detail_class_num, dropout_p=dropout_p
        )
        if freeze_backbone:
            for param in self.backbone.parameters():
                param.requires_grad = False
            for param in self.main_head.parameters():
                param.requires_grad = True
            for param in self.detail_head.parameters():
                param.requires_grad = True

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        features = self.backbone(x)
        return self.main_head(features), self.detail_head(features)

    def get_model(self) -> nn.Module:
        return self


class ResNet18TwoHeadV2Model(BaseClassifierModel):
    """v2: ResNet18 backbone + fixed 5-way main head + fine identity head.

    ``forward`` returns ``(main_output, fine_output)``.

    The two heads differ from v1 in what they are asked to predict. The main
    head has exactly 5 outputs (BACKGROUND, ITEM, MONSTER, NPC, PLAYER) and
    WINDOW is gone from it, because the bot never acts on a window. The fine
    head predicts identity -- a monster species, an item kind -- instead of a
    level band. A level band is not a visual property (a level-8 orc and a
    level-37 archer share nothing to see), so v1 asked the network to learn a
    function of the image that does not exist; a species is exactly one
    sprite. The level then comes from a lookup table, which is both exact and
    changeable without retraining. See ``label_tables.py``.

    Keeping the heads independent is deliberate: requiring both of them to
    agree before the bot treats something as a monster is what makes calling
    a person or a patch of background a monster nearly impossible.
    """

    def __init__(
        self,
        class_num: int,
        fine_class_num: int,
        freeze_backbone: bool = True,
        dropout_p: float = 0.3,
        fine_hidden: int = 256,
        pretrained: bool = True,
    ):
        super().__init__()
        self.backbone = ResNet18Backbone(pretrained=pretrained)
        self.main_head = MainHead(
            self.backbone.out_features, class_num, dropout_p=dropout_p
        )
        self.fine_head = FineHead(
            self.backbone.out_features, fine_class_num,
            hidden=fine_hidden, dropout_p=dropout_p,
        )
        # Plain dict attribute: not a Parameter, so it stays out of the state
        # dict while still letting the trainer record how to rebuild this model.
        self.arch_info = {
            "architecture": "resnet18_twohead_v2",
            "class_num": class_num,
            "fine_class_num": fine_class_num,
            "dropout_p": dropout_p,
            "fine_hidden": fine_hidden,
        }
        self.set_trainable(backbone=not freeze_backbone, main=True, fine=True)

    def set_trainable(
        self,
        backbone: Optional[bool] = None,
        main: Optional[bool] = None,
        fine: Optional[bool] = None,
    ) -> None:
        """Enable or disable gradients per part; ``None`` leaves a part alone.

        Used for staged training: heads first on a frozen backbone, then the
        whole network, and optionally the main head frozen once it is good so
        fine-head fine-tuning cannot degrade the combat-critical output.
        """
        for flag, module in (
            (backbone, self.backbone),
            (main, self.main_head),
            (fine, self.fine_head),
        ):
            if flag is None:
                continue
            for param in module.parameters():
                param.requires_grad = flag

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        features = self.backbone(x)
        return self.main_head(features), self.fine_head(features)

    def get_model(self) -> nn.Module:
        return self


class ModelFactory:
    """Builds any registered model from a configuration string.

    Register new architectures with ``@ModelFactory.register("name")``.
    Reserved-but-unimplemented names in ``_future`` raise a clear
    ``NotImplementedError`` so future models can be wired up later.
    """

    _registry: dict = {}
    _future = {"efficientnet"}

    @classmethod
    def register(cls, name: str):
        def decorator(model_cls):
            cls._registry[name] = model_cls
            return model_cls
        return decorator

    @classmethod
    def create(
        cls,
        architecture: str,
        num_classes: int,
        **kwargs,
    ) -> nn.Module:
        if architecture in cls._future:
            raise NotImplementedError(
                f"Architecture '{architecture}' is reserved but not implemented yet."
            )
        if architecture not in cls._registry:
            raise ValueError(
                f"Unsupported architecture: {architecture}. "
                f"Registered: {sorted(cls._registry)}. "
                f"Reserved (future): {sorted(cls._future)}."
            )
        return cls._registry[architecture](num_classes, **kwargs).get_model()

    @classmethod
    def from_checkpoint(cls, checkpoint: dict, **overrides) -> nn.Module:
        """Rebuild the matching architecture from a saved checkpoint.

        The trainer stores ``architecture`` and ``arch_info`` next to the
        weights. If those keys are missing (older files), the state-dict
        prefixes ``fine_head.`` / ``detail_head.`` / ``head.`` pick the class.
        ``overrides`` replace any reconstructed constructor argument.
        """
        state = (
            checkpoint["model_state_dict"]
            if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint
            else checkpoint
        )
        state = remap_legacy_state_dict(state)
        architecture = (
            overrides.pop("architecture", None)
            or (checkpoint.get("architecture") if isinstance(checkpoint, dict) else None)
            or architecture_from_state(state)
        )
        info = dict(checkpoint.get("arch_info") or {}) if isinstance(checkpoint, dict) else {}
        info.update(overrides)
        # Checkpoint already holds backbone weights; skip ImageNet download
        # (also avoids sys.stdout=None crashes under GUI / windowed launches).
        info.setdefault("pretrained", False)

        if architecture == "resnet18_twohead_v2":
            class_num = info.get("class_num") or state["main_head.fc.bias"].shape[0]
            fine_class_num = info.get("fine_class_num") or state["fine_head.fc.bias"].shape[0]
            if "fine_hidden" not in info:
                hidden_key = "fine_head.body.1.weight"
                info["fine_hidden"] = (
                    int(state[hidden_key].shape[0]) if hidden_key in state else 0
                )
            return cls.create(
                architecture,
                class_num,
                fine_class_num=fine_class_num,
                freeze_backbone=info.get("freeze_backbone", False),
                dropout_p=info.get("dropout_p", 0.3),
                fine_hidden=info.get("fine_hidden", 256),
                pretrained=info.get("pretrained", False),
            )
        if architecture == "resnet18_multihead":
            class_num = info.get("class_num") or state["main_head.fc.bias"].shape[0]
            detail_class_num = (
                info.get("detail_class_num") or state["detail_head.fc.bias"].shape[0]
            )
            return cls.create(
                architecture,
                class_num,
                detail_class_num=detail_class_num,
                freeze_backbone=info.get("freeze_backbone", False),
                dropout_p=info.get("dropout_p", 0.3),
                pretrained=info.get("pretrained", False),
            )
        class_num = info.get("class_num") or state["head.fc.bias"].shape[0]
        return cls.create(
            architecture,
            class_num,
            freeze_backbone=info.get("freeze_backbone", False),
            dropout_p=info.get("dropout_p", 0.3),
            pretrained=info.get("pretrained", False),
        )


def architecture_from_state(state_dict: dict) -> str:
    """Pick the registered name from the prefixes in a state dict."""
    keys = state_dict.keys()
    if any(key.startswith("fine_head.") for key in keys):
        return "resnet18_twohead_v2"
    if any(key.startswith("detail_head.") for key in keys):
        return "resnet18_multihead"
    return "resnet18"


_LEGACY_BACKBONE_PREFIXES = {
    "conv1", "bn1", "relu", "maxpool", "avgpool",
    "layer1", "layer2", "layer3", "layer4",
}


def remap_legacy_state_dict(state_dict: dict) -> dict:
    """Translate pre backbone/head state dict keys into the nested structure.

    Legacy (flat) keys, e.g. ``conv1.weight``, ``layer4.1.bn2.weight``,
    ``fc.weight`` -> nested ``backbone.conv1.weight``, ``head.fc.weight``.
    State dicts that already use the nested structure are returned unchanged.
    """
    if "fc.weight" not in state_dict or "head.fc.weight" in state_dict:
        return state_dict
    remapped = {}
    for key, value in state_dict.items():
        top = key.split(".", 1)[0]
        if top in _LEGACY_BACKBONE_PREFIXES:
            remapped[f"backbone.{key}"] = value
        elif top == "fc":
            remapped[f"head.{key}"] = value
        else:
            remapped[key] = value
    return remapped


def load_backbone_weights(model: nn.Module, checkpoint_path: str) -> None:
    """Load only the trained ``backbone.*`` weights into an existing model.

    Useful for transfer learning: train a model on one dataset, then reuse
    its feature extractor (the backbone) as a pretrained starting point for
    a new task. The head (``head.*`` / ``main_head.*`` / ``detail_head.*`` /
    ``fine_head.*``) is intentionally NOT loaded, so the new model can have
    any number of classes.

    Accepts a raw state dict, a legacy flat state dict, or a full checkpoint
    dict saved by the Trainer (which stores ``model_state_dict``).
    """
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    state = checkpoint["model_state_dict"] if "model_state_dict" in checkpoint else checkpoint
    state = remap_legacy_state_dict(state)

    backbone_state = {
        key[len("backbone."):]: value
        for key, value in state.items()
        if key.startswith("backbone.")
    }
    if not backbone_state:
        raise ValueError(
            f"No 'backbone.*' weights found in {checkpoint_path}. "
            f"Keys seen: {sorted(state)[:10]}"
        )

    missing, unexpected = model.backbone.load_state_dict(backbone_state, strict=True)
    print(f"Loaded backbone weights from {checkpoint_path} "
          f"({len(backbone_state)} tensors; missing={len(missing)}, "
          f"unexpected={len(unexpected)})")


ModelFactory.register("resnet18")(ResNet18Model)
ModelFactory.register("resnet18_multihead")(ResNet18MultiHeadModel)
ModelFactory.register("resnet18_twohead_v2")(ResNet18TwoHeadV2Model)
