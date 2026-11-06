# -*- coding: utf-8 -*-
"""
control.i18n — 한/중/영 문자열 (UI 다국어)

  T = I18n("ko"); T("connect")      # '연결'
  T.set("zh")
"""

LANGS = [("ko", "한국어"), ("zh", "中文"), ("en", "English")]

_S = {
    # 창/연결
    "app_title": {"ko": "control — 시퀀스 테스트 UI", "zh": "control — 序列测试界面", "en": "control — Sequence Test UI"},
    "lang": {"ko": "언어", "zh": "语言", "en": "Language"},
    "conn_opts": {"ko": "연결 / 옵션", "zh": "连接 / 选项", "en": "Connection / Options"},
    "mode": {"ko": "방식", "zh": "方式", "en": "Mode"},
    "mode_tcp": {"ko": "TCP", "zh": "TCP", "en": "TCP"},
    "mode_serial": {"ko": "시리얼", "zh": "串口", "en": "Serial"},
    "mode_virtual": {"ko": "가상", "zh": "虚拟", "en": "Virtual"},
    "hostport": {"ko": "주소", "zh": "地址", "en": "Host"},
    "serial_port": {"ko": "포트", "zh": "端口", "en": "Port"},
    "find_port": {"ko": "포트찾기", "zh": "查找端口", "en": "Find port"},
    "connect": {"ko": "연결", "zh": "连接", "en": "Connect"},
    "disconnect": {"ko": "해제", "zh": "断开", "en": "Disconnect"},
    "screen_wh": {"ko": "화면 W x H", "zh": "屏幕 W x H", "en": "Screen W x H"},
    "chk_feedback": {"ko": "정확 절대좌표(폐루프 피드백)", "zh": "精确绝对坐标(闭环反馈)", "en": "Accurate absolute (closed-loop)"},
    "chk_guard": {"ko": "사용자 간섭 시 정지", "zh": "用户干扰时暂停", "en": "Pause on user interference"},
    "chk_noaccel": {"ko": "포인터 가속 끄기(정확도)", "zh": "关闭指针加速(精确)", "en": "Disable pointer accel (precision)"},
    "pause_s": {"ko": "정지(초)", "zh": "暂停(秒)", "en": "Pause(s)"},
    "resume_s": {"ko": "재개(초)", "zh": "恢复(秒)", "en": "Resume(s)"},
    "st_disconnected": {"ko": "미연결", "zh": "未连接", "en": "Disconnected"},
    "st_connected": {"ko": "연결됨", "zh": "已连接", "en": "Connected"},
    "st_virtual": {"ko": "가상(테스트) 연결됨", "zh": "虚拟(测试)已连接", "en": "Virtual (test) connected"},
    "st_running": {"ko": "실행 중...", "zh": "运行中...", "en": "Running..."},
    "st_done": {"ko": "완료", "zh": "完成", "en": "Done"},
    "st_stopped": {"ko": "정지됨", "zh": "已停止", "en": "Stopped"},
    "st_error": {"ko": "오류", "zh": "错误", "en": "Error"},
    # 시퀀스 편집
    "seq_title": {"ko": "시퀀스 (실행 순서)", "zh": "序列 (执行顺序)", "en": "Sequence (run order)"},
    "col_time": {"ko": "시각(s)", "zh": "时刻(s)", "en": "Time(s)"},
    "col_kind": {"ko": "종류", "zh": "类型", "en": "Kind"},
    "col_detail": {"ko": "세부", "zh": "详情", "en": "Detail"},
    "time_s": {"ko": "시각(초)", "zh": "时刻(秒)", "en": "Time(s)"},
    "kind": {"ko": "종류", "zh": "类型", "en": "Kind"},
    "add": {"ko": "추가", "zh": "添加", "en": "Add"},
    "del": {"ko": "선택삭제", "zh": "删除选中", "en": "Delete"},
    "clear": {"ko": "전체삭제", "zh": "全部清除", "en": "Clear"},
    "up": {"ko": "▲", "zh": "▲", "en": "▲"},
    "down": {"ko": "▼", "zh": "▼", "en": "▼"},
    "capture": {"ko": "현재 마우스 위치", "zh": "当前鼠标位置", "en": "Capture cursor"},
    # 실행/로그
    "run": {"ko": "▶ 실행", "zh": "▶ 运行", "en": "▶ Run"},
    "stop": {"ko": "■ 정지", "zh": "■ 停止", "en": "■ Stop"},
    "save": {"ko": "저장", "zh": "保存", "en": "Save"},
    "load": {"ko": "불러오기", "zh": "读取", "en": "Load"},
    "log_title": {"ko": "로그", "zh": "日志", "en": "Log"},
    "t_now": {"ko": "t = {v:.2f} s", "zh": "t = {v:.2f} s", "en": "t = {v:.2f} s"},
    # 종류(코드->표시)
    "k_move": {"ko": "이동", "zh": "移动", "en": "Move"},
    "k_click": {"ko": "클릭", "zh": "单击", "en": "Click"},
    "k_dclick": {"ko": "더블클릭", "zh": "双击", "en": "Double-click"},
    "k_drag": {"ko": "끌기", "zh": "拖拽", "en": "Drag"},
    "k_wheel": {"ko": "휠", "zh": "滚轮", "en": "Wheel"},
    "k_key": {"ko": "키", "zh": "按键", "en": "Key"},
    "k_hotkey": {"ko": "핫키", "zh": "组合键", "en": "Hotkey"},
    "k_text": {"ko": "텍스트", "zh": "文本", "en": "Text"},
    "k_wait": {"ko": "대기", "zh": "等待", "en": "Wait"},
    # 버튼/파라미터
    "b_left": {"ko": "좌", "zh": "左", "en": "Left"},
    "b_right": {"ko": "우", "zh": "右", "en": "Right"},
    "b_middle": {"ko": "가운데", "zh": "中", "en": "Middle"},
    "p_duration": {"ko": "기간(ms)", "zh": "时长(ms)", "en": "Duration(ms)"},
    "p_button": {"ko": "버튼", "zh": "按钮", "en": "Button"},
    "p_hold": {"ko": "누름(ms)", "zh": "按住(ms)", "en": "Hold(ms)"},
    "p_cps": {"ko": "속도(cps)", "zh": "速度(cps)", "en": "Speed(cps)"},
    # 메시지
    "msg_no_step": {"ko": "시퀀스가 비어 있습니다.", "zh": "序列为空。", "en": "Sequence is empty."},
    "msg_need_conn": {"ko": "먼저 연결하세요.", "zh": "请先连接。", "en": "Connect first."},
    "msg_bad": {"ko": "값을 확인하세요: {f}", "zh": "请检查数值: {f}", "en": "Check value: {f}"},
    "msg_saved": {"ko": "저장했습니다.", "zh": "已保存。", "en": "Saved."},
    "msg_loaded": {"ko": "불러왔습니다.", "zh": "已读取。", "en": "Loaded."},
}

_BTN = {"좌": "b_left", "우": "b_right", "가운데": "b_middle",
        "Left": "b_left", "Right": "b_right", "Middle": "b_middle",
        "左": "b_left", "右": "b_right", "中": "b_middle"}


class I18n(object):
    def __init__(self, lang="ko"):
        self.set(lang)

    def set(self, lang):
        self.lang = lang if lang in dict(LANGS) else "ko"

    def __call__(self, key, **kw):
        d = _S.get(key, {})
        s = d.get(self.lang) or d.get("en") or key
        return s.format(**kw) if kw else s

    def button(self, name):
        return self(_BTN.get(name, "b_left"))
