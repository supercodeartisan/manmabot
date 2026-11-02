# Decision change log

## 2026-11-02 — Y uses a live keyboard slot; a missed key does not press Enter

Intent: The invite popup closed because Y never reached the game and Enter still dismissed it. A `/초대` line was logged as typed when the strokes went to whichever window was in front.
Shared: `ec_ic_open` keeps the first keyboard slot whose key-up send returns 1. `ec_run` skips Enter when any key failed, and Escape-closes a chat line it had opened. A line is a failure when the game is not the foreground window. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are. The 20s invite clock is unchanged.
Affects: party `/초대` and invite Y. The running bot keeps the old DLL until it is restarted.
Consent: user (update).
Result: DLL rebuilt. Not run as a party join.

## 2026-11-02 — reconnect resumes from game memory, not a new invite

Intent: A member socket drop is not a failed party join. On reconnect the leader waits for a new `member_state` before another `/초대`. A name already in party memory stays joined. `InviteAccepter` keeps watching the popup across the drop and does not press Y until the policy names the inviter.
Shared: `MemberStates.hold_until_fresh` on the dropped socket id. `LeaderInvites` 20s clock and `InviteHold` stay. Reconnect wait is 2s plus jitter, capped at 15s. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are. `PartyMemberManager.decide` is unchanged.
Affects: one member's invite gate and the monitor words (RECONNECTING / ACCEPTING / IN PARTY). Other members and the leader hunt are not reset.
Consent: user (recover the interrupted step from game state after reconnect).
Result: not run in game.

## 2026-11-02 — party monitor Invite / Y focuses the game

Intent: Invite from the monitor typed only after the user clicked the game. The monitor is the foreground window, so the worker's later `SetForegroundWindow` is refused.
Shared: the Invite and Y+Enter clicks call `bring_game_to_front` on the UI thread before the queued `deliver_chat` / `type_accept_key`. Always-on-top is dropped until that action finishes. The worker focuses again at the start of the same drain. Automatic invites still use `deliver_chat` → `ec_run`; automatic Y still uses `type_accept_key`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: party monitor buttons only.
Consent: user (focus the game automatically; confirm the buttons share the bot path).
Result: not run in the UI.

## 2026-11-02 — Stop disarms the schedule before the next poll

Intent: Stop was restarting the game and opening the party monitor. The Qt shell disarmed the schedule on a queued signal, so the schedule poll still saw an armed session in the STOPPED state and called Start.
Shared: `userStopped` now runs `_disarm_schedule` directly inside `coordinator.stop`, before `_halt` returns. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: Stop button and the stop hotkey. Party forming still does not switch the bot to solo.
Consent: user (Stop starts the game again and the party monitor opens).
Result: not run in the UI.

## 2026-11-02 — party memory unknown, join is memory, one chat queue

Intent: A failed party read must not invite or leave. Popup close after Y is not a join. Monitor Invite / Y+Enter must not type beside the automatic invite.
Shared: `memory_in_party` is True / False / None. `needs_leave` requires this name, the leader name, and a confirmed in-party read. `reported_joined` uses fresh member party memory only. `InviteAccepter` goes `waiting_memory` then `joined`. `PartyChatQueue` is drained once per worker tick; that tick skips the matching automatic line. Forming deadline is not moved on reconnect. Hunt waits only for roster rows with Wait checked (default on). On unchecks a name. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: leader invite and leave, member accept, party monitor buttons, Party tab roster, when forming holds the hunt.
Consent: user (implement the party invite/maintain corrections).
Result: not run in game. Discovery approval and a second rally for late members are not in this change. Restart the bot to load it.

## 2026-11-01 — invite accept is Y then Enter

Intent: The invite popup accepts only when Y is followed by Enter. Y alone does not confirm.
Shared: `type_accept_key` now calls `GameChat.send("y", open_chat=False, press_enter=True)`. One `ec_run` types physical Y, then physical Enter, while English is still held. Chat is not opened. The monitor button is the same call. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member invite accept, and the party monitor Y+Enter button.
Consent: user (Y and Enter are both required).
Result: not run in game.

## 2026-11-01 — party monitor can type /초대 and Y

Intent: From the party monitor, send one invite line and press Y through the same bot path as Start (`send_chat_line` / `type_accept_key` → `ec_run`).
Shared: `PartyMonitorWindow` name field, Invite button (`invite_command` → `deliver_chat`), Y button (`type_accept_key`). Both run off the UI thread. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: the party monitor window only. Leader invite timing and member popup accept are unchanged.
Consent: user (run these from the invite monitor, including Y).
Result: not run in the UI yet.

## 2026-11-01 — invite Y uses the same ec_run as the admin exe

Intent: Member Y still switched the IME from Python while the bot window was in front, then fell back to the hunt keyboard. The popup needs one physical Y with the game in front and the IME in English.
Shared: ASCII-only `ec_run` (`y`, no chat open, no Enter) focuses the game, clears 한글 mode, sends the key, holds English 150 ms, then restores the previous mode. `type_accept_key` is only that call. The hunt Y fallback is gone. `/초대` still uses 한 mode. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member invite accept. A lone ASCII chat line takes the same English path.
Consent: user (Y must match the admin exe).
Result: DLL rebuilt (`BUILD_OK`). Not run in game. Restart the bot so it loads the new DLL.

## 2026-11-01 — bot invite keeps the game in front and switches 한

Intent: The bot is already elevated, but `/초대` still followed the Windows input language. The admin exe does not, because it is a fresh process that is allowed to take the foreground and the game thread applies the Korean layout. The bot window takes focus back during the typing sleep.
Shared: `ec_force_foreground` unlocks foreground (`AllowSetForegroundWindow` / `LockSetForegroundWindow`) before `SetForegroundWindow`. `ec_hangul_prepare` loads layout 0412 without activating it on the caller thread, then `SendMessageTimeout` of `WM_INPUTLANGCHANGEREQUEST` on the game thread, and retries 한 mode once after focusing the game. `ec_run` puts the game in front again before the layout switch, before each character, and before the final Enter. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: every `ec_run` caller (bot party invite / leave, member Y via `GameChat.send`, and both CLIs). Hunt keyboard and Pico are unchanged.
Consent: user (bot must have the same effect as the admin exe; bot is already admin).
Result: DLL rebuilt (`BUILD_OK`). Not run in game. The running bot keeps the old DLL until it is restarted.

## 2026-11-01 — member runs from party memory with no websocket

Intent: Follow and combat must run from party memory when the leader socket is down or was never configured. The socket stays optional and only carries policy and rally.
Shared: member worker no longer calls `decide_survival` while the socket is pending. Missing leader IP no longer stops the worker. `PartyMemberManager.decide` is unchanged. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member Start. Not-in-party still waits inside `decide` (`leader_missing`) until party memory shows a leader. Leader path unchanged.
Consent: user (client must work from memory reads with no websocket).
Result: not run in game.

## 2026-11-01 — member already in party does not wait on the socket

Intent: Party memory already showed `in_party` with leader 매력여기사, but the member stayed on `decide_survival` (`waiting_leader_socket`) until `192.168.9.27:8765` connected. Follow should start from the in-game party; the socket is only for policy and rally.
Shared: worker gate around `_member_socket_pending`. Still HP-only when party memory does not say in-party. `PartyMemberManager.decide` itself is unchanged. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member Start when already in an in-game party and the leader socket is still connecting. Not-yet-joined members still wait. Leader path unchanged.
Consent: user (if the client is already in the party, enter it; do not keep waiting).
Result: not run in game.

## 2026-11-01 — party frame checks before workflow

Intent: Bad party frames must not book an invite, a policy ack, or a member order.
Shared: `frame_check` drops non-objects, unknown types, control characters, names over 16, a member frame that says it is the leader, a hello whose name does not match `from`, and a leader policy/rally with missing fields. Unnamed `from=member` still stays Unidentified and is not invited. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: party socket ingest only.
Consent: user (put checks in so errors do not get through).
Result: not run in game.

## 2026-11-01 — member name from MyPlayer entity

Intent: The member hello had no character name because `PlayerState` has no name field. The enttrack snapshot already has a `MyPlayer` row with `name`.
Shared: `_player_chat_name` reads that row first. Party monitor shows it as Self. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: party hello / member_state sender name and the monitor label. Hunt targeting is unchanged (`MyPlayer` stays off the click list).
Consent: user (read MyPlayer and display it).
Result: not run in game.

## 2026-11-01 — P0 member discovery (hello, pending, empty-roster listen)

Intent: Add a discovery layer in front of the existing party workflow. Unknown sockets must not be dropped; empty roster must still listen. Hunt brains stay as they are.
Shared: `_party_server_on` (listen) vs `_party_leader_on` (invite/rally/turret). `MemberDiscovery` keeps unmatched hellos as PENDING/UNIDENTIFIED/CONFLICT. Matched names still go through `member_states` / invite / rally. Members without a roster seat do not overlay policy or consume rally. No `UNKNOWN` name, no `try_unstick_escape` / `begin_retreat` / `apply_hp_actions` / login changes.
Affects: leader socket start (empty roster listens, workflow waits). Member hello after a real `identity.name`. Party monitor Discovery metric. Approve/reject UI is P1.
Consent: user (discovery layer P0 spec).
Result: not run in game.

## 2026-10-31 — invite accept Y uses the same enter_chat ec_run as /초대

Intent: `ec_press_key` is not in enter_chat.dll 1.0.0, so member Y could not use the invite typing module. User asked to use the same API as inviting.
Shared: `type_accept_key` calls `GameChat.send("y", open_chat=False, press_enter=False)` under English IME. DLL `ec_run` sends ASCII via Interception when Hangul IME is not active (so Y is a physical key; mixed `/초대` names stay WM_CHAR). Hunt Y remains the fallback. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member invite Y. Leader `/초대` Hangul path unchanged.
Consent: user (use the inviting enter_chat API for Y).
Result: not run in game.

## 2026-10-31 — member assist beats follow

Intent: Single member walked to the leader (`follow_off_ui` / turret yard / `follow_combat_near`) and only then assisted. Assist must win over moving.
Shared: `decide_policy` takes ASSIST/CLOSE_IN as soon as `assist_ready`, before any FOLLOW, and without the assist-leash gate. Out of range is CLOSE_IN to the mob, not FOLLOW to the leader. HP / defend / join-map stay above. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member combat vs follow. Follow still runs when there is no assist target. Assist leash still gates turret yard rejoin and `follow_combat_leash`.
Consent: user (just make assist higher than moving).
Result: not run in game.

## 2026-10-31 — member follow closes on the leader, no reverse to a behind-slot

Intent: Single member did not stop within `stop_tiles` when the leader stopped, and sometimes walked the opposite way. Follow was walking to a Reynolds behind-slot, a random cardinal stand, or the turret ring seat — never "arrive near the leader and hold".
Shared: `follow_kind` is a rubber-band on distance to the leader (close until `stop_tiles`, no slot/stand). Manager FOLLOW uses field descent toward the leader; behind-slot / trail / turret seat are not click goals. Turret ring `FOLLOW turret_seat` removed (yard rejoin stays). `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member follow / idle hold only. Multi-member turret spread no longer walks to a ring seat; they hold inside `stop_tiles`.
Consent: user (stop reversing; leader stops → member reaches stop_tiles).
Result: not run in game.

## 2026-10-31 — member Y reached the bot UI, not the invite popup

Intent: Member log showed `Y key pressed #1/#2/#3` then `Y FAILED: popup still open`. `_press()` returning "" only meant hunt `key_down("y")` did not throw. Interception/pico keys go to the foreground window; the bot UI was in front, so Y never hit LC. `enter_chat.dll` in this tree is 1.0.0 with no `ec_press_key`, so the DLL path never runs. First policy contact also `reset()` the accepter mid-press, starting a second 3-press cycle.
Shared: hunt Y now AttachThreadInput-focuses LC and does not send Y unless the game is in front; the traffic line records `hunt|enter_chat`, backend, IME. First-contact session no longer resets `InviteAccepter`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member invite accept only.
Consent: user (check Y pressed 3× popup still open).
Result: not run in game.

## 2026-10-31 — member invite Y without enter_chat.dll

Intent: The member saw the invite popup (uidialog confirm parse works) but Y failed: `enter_chat.dll not found` on `D:\ManmabotV1_final_final_final\...` (that tree has no built DLL). Accept must still press Y via the hunt keyboard.
Shared: `accept.type_accept_key` tries enter_chat `ec_press_key`, then hunt `key_down("y")` with English IME. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member invite accept only.
Consent: user (client accept failing).
Result: not run in game.

## 2026-10-31 — uidialog confirm text reaches invite accept; chat typed logs IME

Intent: Member never saw the in-game invite popup. `uidialogmon` already prints Yes/No confirm text, but `lc_view.uidialog()` kept only window labels, so `invite_popup.party_invite` always got an empty `confirm` list. Leader `typed` also hid IME/char counts, so a Hangul `/초대` that went out as jamo still looked successful.
Shared: `lc_view.parse_uidialog_text` fills `confirm` from status `msg=` and `[+] CONFIRM` lines; sensors accept a snapshot that has `confirm`. `deliver_chat` logs `chars`/`keys`/`ime` on success and fails when `failed>0`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member invite Y (popup pattern). Leader invite log detail only.
Consent: user (fix uidialog confirm parse + DLL typed honesty).
Result: not run in game.

## 2026-10-31 — leader start wait 10 min

Intent: The forming window before hunt (all joined → formed, else late + keep inviting) was 5 min. User asked for 10 min so a multi-member roster has more time to connect, ACK, and arrive.
Shared: `invite.START_WAIT_S` and `leader_rally.WAIT_TIMEOUT_S` (fallback when no invite deadline). Rally still uses the same start-wait deadline. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: leader hold/rally/hunt start time with a named roster. Invites still have no cut-off after the window.
Consent: user (set start wait to 10 mins).
Result: not run in game.

## 2026-10-31 — empty roster does not start leader party

Intent: With no member names, the leader still armed the party (websocket listen, session, rally hooks, monitor pipeline). Party must not start at all until the roster has at least one name; the bot hunts solo.
Shared: `_party_leader_on` now requires `_leader_roster_ready`. `_start_party_socket` / `_ensure_party_log` / nav hooks / invite setup all follow that gate. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks, hunt loop stay as they are.
Affects: leader Start with an empty Party-tab roster. Named roster unchanged.
Consent: user (empty roster must not start party).
Result: not run in game.

## 2026-10-31 — leader workflow: rally/hunt not done while connect is waiting

Intent: The party monitor listed Server → Connect → Policy → Invite → Rally → Hunt as a sequence, but an empty roster skipped rally to ``done`` and the phase became hunting, so Rally/Hunt went green while Connect/Policy/Invite were still waiting. With a roster, start rally also began on the first tick.
Shared: `leader_workflow` later steps stay off/wait until connect has members; `LeaderStartRally.begin` with no names stays ``off`` (does not `skip()` to ``done``); `_leader_may_begin_start_rally` waits for a member socket and for the invite start-wait to finish (or the party to form). Forming still uses the existing hold-ground window so the leader does not full-hunt while inviting. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: leader party monitor badges; when start rally begins. Empty roster: leader still farms; Rally/Hunt stay off. Named roster: Rally starts after connect + invite window, still bounded by the same start-wait deadline.
Consent: user (rally/hunt active while connect/policy/invite waiting).
Result: not run in game.

## 2026-10-30 — member heal/buff on the policy ladder; HP while waiting for the leader socket

Intent: Item 7 was two ladders, not a broken heal. Live heal/buff returned from `apply_party_support` before gather/policy, while `decide_policy` never emitted HEAL/BUFF and `intent_for_kind` idled those kinds. Unify: stash support, skip gather when heal/buff is needed (heal still beats the start rally), policy emits HEAL/BUFF first, manager returns the stash. Item 10: leftover `WorldNavHooks` cleared at `_worker` start (party-off Start already cleared them); `merge_leader_policy` imports `comms.orders` not `websocket.party_orders`; member Start enters the bot loop and runs HP-only (`decide_survival`) until the leader socket connects. There is no 60 s connect timeout — 30 s is log cadence. Empty leader IP still fails immediately.
Shared: `decide_policy` / `PolicyInput.need_heal`/`need_buff`; `PartyMemberManager.decide` / `decide_survival`; `BotController._start_party_client` / `_member_socket_pending`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are. `apply_party_support` and `party_critical_escape` still own in-place HP and the retreat gate.
Affects: party members only (policy order, start-rally vs heal, first-connect wait). Leader and solo decide paths are unchanged. After the first connect, a socket drop still farms on the last policy.
Consent: user (item 7 policy order + item 10 leftover hooks / import boundary / HP before connect).
Result: not run in game.

## 2026-10-29 — start rally yields to combat on the member

Intent: A live rally order must not keep the member walking to the pin while the leader is already fighting a few tiles off it. Crisis retreat and in-place heal/buff still run first. After the fight the member can finish the rally walk (arrival is not marked on yield).
Shared: `PartyMemberManager._maybe_hunt_gather` / `_rally_yields_to_combat`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are. `apply_party_support` still runs before gather.
Affects: party members during the start rally only. Solo and leader hold-ground are unchanged.
Consent: user (item 4, rally before assist).
Result: not run in game.

## 2026-10-29 — unnamed policy ack books each member by client_id

Intent: Two member bots that start together both send `from=member` before they know their character name. The leader used to keep that ack only when exactly one roster name was still unconfirmed, so `/초대` never went out.
Shared: `PolicyAcks.note` / `MemberStates.note` / `InviteAccepts.note` bind `client_id` to the next free roster name in order. Member Start makes one 8-hex id and puts it on `policy_ack`, `member_state`, and `invite_accept`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: leader invite gate when two or more members connect before they are in the in-game party.
Consent: user (policy ACK name matching).
Result: not run in game.

## 2026-10-29 — already-formed party skips /초대, socket beep

Intent: On party Start, read party memory first. If this character is already in a party, do not type `/초대` (or `파티탈퇴` when identity is unknown). Connect the websocket and send a `beep` test frame instead. Missing roster names are still invited.
Shared: `invite.already_in_party` / `LeaderInvites.start` seed-from-memory; `accept.InviteAccepter` ignores the popup while `in_party`; wire type `beep`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: leader setup and member invite-accept at Start. Rally / hunt after that is unchanged.
Consent: user (after leftover-leader-hooks fix; “go on” for already-organized skip-invite + beep).
Result: not run in game.

## 2026-10-29 — leftover leader role does not run party hooks

Intent: Enable party off means a solo Start. A saved `party_role=leader` must not install rally hooks, hold-ground, invites, policy, or decision publish.
Shared: `BotController._party_leader_on` (requires `party_enabled` and role leader). `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: Start when the Party checkbox is off. A previous leader role in the schedule no longer waits on `party.hold_ground`.
Consent: user (fix leftover leader hooks first; party-already-formed skip-invite is next).
Result: not run in game.

## 2026-10-28 — hunt input: toolbar choice is not replaced by a schedule

Intent: choosing Interception on the toolbar must be the hunt transport. A schedule apply was able to write `input_backend` back onto the profile.
Shared: schedules no longer store or apply `input_backend` / `pico_com` / `pico_baud`. The choice is saved with the app state. Start logs `Hunt input:`.
Affects: which transport the next hunt start opens. Click/key behavior unchanged.
Consent: user reported Interception was selected and the start still opened the Pico.
Result: the 05:56 start logged `Pico data COM was not found` before the 05:57 save of `interception`. Not re-run after this change.

## 2026-10-22 — hunt input: live data COM only, shown as a label

Intent: choosing Raspberry Pi should read the plugged-in data port. A saved COM must not stay selected, including the REPL.
Shared: `find_pico_data_port` is the hunt port. `resolve_pico_port` ignores a saved name. `MANMABOT_PICO_COM` still overrides. Toolbar and driver dialogs show that port as a label.
Affects: which COM the next hunt start opens. Click/key behavior unchanged.
Consent: user asked to drop the port selector and the remembered COM, and to detect when Raspberry Pi is selected.
Result: not run as a hunt session. A scan of the plugged-in board is what produced COM5 earlier; that number is not stored in the code.

## 2026-10-22 — hunt input: Detect COM button on the main toolbar

Intent: the COM box can keep a saved port that is still plugged in, including the REPL. Users need one button that writes the data port.
Shared: toolbar `Detect COM` calls `find_pico_data_port` and saves `pico_com`. Visible only while Raspberry Pi is selected. Stopped sessions only.
Affects: which COM the next hunt start opens. Click/key behavior unchanged.
Consent: user asked for a detect button on the bot control UI.
Result: live ports at the time of the request were COM4 (`x.0`, REPL) and COM5 (`x.2`, data). The button selects COM5.

## 2026-10-22 — hunt input: Pico data COM is filled from Windows

Intent: plugging the Pico should not require typing a COM name, and a saved name that disappeared after a different USB socket should be replaced.
Shared: `find_pico_data_port` / `resolve_pico_port` (vendor `0x2E8A` or `0x239A`, hardware id `x.2`, same as the Pico lab scripts). A saved COM that is still in the Windows list is kept. Toolbar, driver dialogs, and `prepare` use that. `MANMABOT_PICO_COM` still overrides.
Affects: which serial port hunt input opens. Click/key behavior unchanged.
Consent: user asked to auto-get the COM and combine it with a manual choice.
Result: not run against a plugged-in board.

## 2026-10-22 — hunt input: Interception or Pico, chosen in the driver window

Intent: farm clicks and keys can use either the Interception driver or the Pico HID board. Both stay available. Login and party chat keep Interception.
Shared: `app._05_action.input_backend` (`InterceptionHuntInput`, `PicoHuntInput`). `MouseController` / `KeyboardController`, talking-scroll wheel, and shop scroll call it. Profile `input_backend`, `pico_com`, `pico_baud` (trial `other`). Driver setup (Qt and Tk) radios plus data COM. `bot_input_released` drops devices only when the farm path holds Interception, so a Pico session does not close COM for chat.
Affects: hunt mouse, keyboard, and scroll transport. Untouched: decision, retreat, HP, login `win.interception`, enter_chat DLL.
Side effect candidates: Pico aim adds a short cursor check before each click; pointer acceleration is off while a Pico hunt session is open and restored on Stop; a failed Pico open stops the farm loop; Interception hunt behavior matches the previous device bind.
Consent: user asked to implement both input modules on the control UI for hunting.
Result: not run on hardware in this change.

## 2026-10-22 — party: start order free (leader / members any order), per-member invites, leader member picker

Intent: only 1:1 tested so far, but real runs have several accounts. The start order was strict: a member stopped if the leader socket was not up within 60 s, and the leader invited only inside a 15 min window from its own Start (late members, or members that left the party, were never invited again). The leader monitor summed all members into one line. User asked for free start order and a member selector to manage members one by one.
Shared:
- Member start (`BotController._start_party_client`): waits for the leader socket with no timeout (30 s log lines, `watch_member` between, Stop cancels); the bot loop is not entered until connected (no movement / combat / HP while waiting — same as the old 60 s wait). Only an empty leader IP still stops with `party_ws_unreachable` (text updated EN/KO/ZH). Snapshot `start_wait` → yellow monitor note.
- `invite.PartyInviter` per member, no cut-off: `START_WAIT_S` = 5 min (was the 15 min window) only bounds the leader's wait before the hunt; states forming → formed | open. Missing at 5 min = `late` (still invited); no `excluded`. Leave detection: joined member whose `member_state` says "not in this party" (fresh, memory readable — `MemberStates.out_of_party`) while the leader memory does not list it, for `LEFT_CONFIRM_S` 10 s → invited again (`left` count).
- `LeaderInvites`: policy re-sent whenever the socket count rises (also after a drop); no `/초대` right after a combat action (`COMBAT_ACTIONS`: attack, potions, depoison, heal, buff, hp_to_mp) unless a due invite waited `COMBAT_HOLD_MAX_S` 60 s; NPC / gate / teleport rule unchanged.
- `leader_rally.WAIT_TIMEOUT_S` 5 min; deadline = start wait end. `comms.ingest.drain_leader_reports`: after the start rally is done, the rally point is not repeated to new sockets — late members follow the leader (existing follow / join_map, no new movement code).
- `member_state` gains `live` (bot state, map/xy from `live_pose_from_state`, hp/mp, brain kind/reason, rally stage/arrived) — rides along, not counted as a change. Name falls back to `_player_chat_name` before the policy is applied. `MemberStates.unnamed_recent` flags frames that could not be booked.
- Monitor: roster rows get `state` (offline / policy_wait / inviting / accepting / late / late_offline / joined / following / ready / not_arrived), `live`, `late`, `left`, per-member `steps` (`workflow.roster_member_steps`). Dashboard: member list with state colours + detail pane (steps, last report, bot, map/XY, HP/MP, brain, invites, left/late, frames mentioning that member); overview table kept; PHASE "START WAIT", INVITE "OPEN".
Affects: party leader invite timing (continues while hunting; delayed by combat), leader start wait (15 → 5 min), member Start (never times out). Untouched: `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, member follow / assist / loot, login, solo decisions, mapId source.
Side effect candidates: a member left running with no leader waits forever (shown yellow); continuous turret combat delays invites up to 60 s; slow-loading members miss the rally and follow instead; an "out" report racing a real join is held 10 s before re-invite.
Consent: user picked wait_forever / per_member / 5 min fixed / list+detail / combat gate "no_combat" / go "all".
Result: party tests 245 OK (2 skipped); new `test_party_free_order.py`, `test_party_invite_setup.py` rewritten (it still expected `/파티` and `POLICY_WAIT_S`), two stale `test_party_rally` cases fixed (recovery frame `from: leader`, drain test profile). Offscreen dashboard render checked with 3 members (hunting / late inviting / late offline) + unnamed warning. Not run live yet.

## 2026-10-22 — party: level-triggered leader↔member sync (`member_state`) + party memory fixed for 26.10.18.2

Intent: live run (leader `party-20261022-052750.log`, member 04:27:55–04:28:50 member clock): the member really joined after Y, but both monitors showed failed / in progress. Causes: (1) party memory blind on both PCs — the party reader used its own stale registry copy (BUILD 26.10.16.1), anchoring failed, `world.last_party` = None (`count=None` in every "Party wait" line), so "in party" was read as "no"; (2) nothing told the leader the member joined — invite notices were fire-and-forget and the leader retyped `/초대` every 20 s while the member was still in its 30 s wait. The user asked for a correct sync/ack system for bots that start at different times, using party memory to confirm the join.
Shared:
- Party memory: `party_listen_reader.default_registry_path` = lc930 registry (same anchors as every other reader) + new `analysis/party/registry/PARTY_SEC17.txt` (party keys only; vfts +0xB5E0, the shift of MAPSUBS and SHOP). `party_listen.c` reports `subs_ok` (PartySubsystem vft found — works outside a party); reader auto-calibrates once over known patch deltas when false. Sensors treat `subs_ok:false` as unknown (None), not "no party". New `analysis/party/build.bat`, `tools/probe_party_vft.py`. Start log: "Party memory: OK / calibrated / PartySubsystem not found".
- Protocol (`app/_06_party/sync.py`): member sends `member_state` every 2 s and on change (session, applied policy id, own party memory, last invite id + accept phase). Leader `MemberStates` keeps the latest per roster name (stale after 7 s, other session ignored); its `policy_id` confirms the policy (legacy `policy_ack` still accepted). `InviteGate`: invite notice resent (same id) every 3 s up to 3× until the member state echoes it; no new `/초대` while the member reports `waiting`/`pressed` for the last id (max 60 s). `PartyInviter.observe` counts a join from leader memory OR the member's report (in party, party leader = this leader).
- `InviteAccepter`: ignores a repeated `invite_id`; `phase`; party memory None → join "unverified" instead of "missed".
- `MemberOrders.ingest` reads `session` only from `from == "leader"` frames (the server relays member frames to every client).
- Monitor: member steps add Sync; Accept / In party use phase and show "unknown" when party memory is unreadable. Leader Connect shows "k/n reporting state", Invite shows joins by member report and holds. Roster In party: YES (source) / NO (red only when both memories are readable) / ?.
Affects: party leader invite timing (fewer `/초대` repeats; retype right after a missed accept), member accept (dedupe), party join detection. Movement, combat, HP, login, solo decisions untouched. Side effect candidate: if the auto-calibrated vft were wrong in a way that still matches PartySubsystem, party member names could read wrong — RC / RC_PLAYER are still checked per member.
Wire: leader and member must run this build together (new `member_state`; an old member still works through `policy_ack` but gives no join report). Deploy to both PCs: Python files, `analysis/party/registry/PARTY_SEC17.txt`, `analysis/lc930/registry/LC930_REGISTRY.txt`, rebuilt `analysis/party/party_listen.dll`.
Consent: user request ("build very successful communication system … recognize the party creation on the memory reading and send ack, and check this on the leader side. fix and implement correctly").
Result: offline simulation (member starts 10 s late, first notice dropped, leader memory blind, member memory readable from 40 s): notice resent at 13 s and accepted, Y at 43.5 s, leader "joined — member report" at 44 s, one `/초대` typed in total. Without the join, `/초대` retyped only after the member reported `missed`. `party_listen.dll` rebuilt. Live party memory check not done (UAC prompt for the elevated probe was cancelled).

## 2026-10-22 — party: invite accept Y as a physical key (typed `y` was ignored)

Intent: live test (leader 05:14–05:16, member clock ≈1 h 3.4 s behind): 4 invites typed, 4 notices received, Y "typed" OK twice (enter_chat status OK), but party memory never showed a join. An ASCII `y` goes out as `WM_CHAR`; the popup only reacts to a key event.
Shared: `accept.type_accept_key` → `GameChat.press_key(0x15)` → enter_chat `ec_press_key` (same typing module, Interception key down/up, needs DLL 1.1.0). `InviteAccepter` logs 5 s after Y whether party memory shows the join (`join_missed` on the monitor Accept step).
Affects: member invite accept only; 30 s delay unchanged. Open: whether the popup stays open 30 s while the leader re-invites every 20 s — the 5 s join check tells.
Consent: fixes the agreed accept path (popup key Y) under the user's "use the invite sender's typing module".
Result: simulated: one scancode 0x15 press at 30 s; join check logs a miss. DLL 1.1.0 export loads. Not run in game.

## 2026-10-22 — party: invite accept 30 s after the notice, typed Y, logic moved to `_06_party`

Intent: user asked for a 30 s wait after the leader's invite notice, Y through the same typing module as the leader's `/초대`, and less party code in `bot_controller`.
Shared: new `app/_06_party/accept.py` `InviteAccepter` (`on_notice` / `tick` / `status` / `reset`): Y via `send_chat_line("y", open_chat=False, press_enter=False)` (enter_chat; ASCII goes as `WM_CHAR`). A repeat notice while one is queued keeps the first due time (the leader repeats every 20 s). No press if party memory shows a join by then. New `app/_06_party/workflow.py` (`leader_workflow` / `member_workflow`) — moved out of `bot_controller`. Controller keeps one hook `_member_invite_accept`. Python wrappers for `ec_press_key` removed (the DLL export stays, unused).
Affects: member invite accept only (timing 0.8 s → 30 s, key path physical scancode → typed `y`). Side effect candidate: if the popup only reacts to a key event and not to `WM_CHAR`, Y does nothing — then switch `type_accept_key` back to a physical key. Supersedes the 0.8 s / scancode part of the entry below.
Consent: user request.
Result: simulated: no press at 29.9 s, one `y` at 30 s despite a 20 s repeat notice; no press when joined meanwhile. Not run in game.

## 2026-10-22 — party: member auto-accepts the invite (Y) on a leader socket notice

Intent: the leader's `/초대` reached the game but the member never accepted. Nothing on the member read the [Yes]/[No] popup (enter_chat only types; no popup / chat memory sensor exists). Now the leader tells the member over the socket right after typing, and the member presses Y.
Shared: new wire type `party_invite` (`to`, `invite_id`, `session`) from `LeaderInvites.tick` after a typed `/초대 <to>` (`announce_invite` → `party_orders.publish_invite`). `MemberOrders` keeps the latest notice (`take_invite`); dropped on a new leader session. Controller `_queue_member_invite_accept` / `_member_invite_accept_tick`: press Y 0.8 s after the notice, once per notice. Skipped when party memory already says in a party, or when the notice names another roster name than this character (an unconfirmed local name never vetoes). Key: new `enter_chat` export `ec_press_key` (ABI 1.1.0, Interception only, no message/SendInput fallback) → `GameChat.press_key` / `press_game_key`, under the same `bot_input_released` handoff as chat.
Affects: member only, in the member tick before `decide`. One Y key press per leader invite (every 20 s until party memory shows the join). Side effect candidate: if the popup is not open (closed by hand, refused, late), Y reaches the game as a plain key. Leader invite timing unchanged. Monitor: member Workflow step `Accept`; leader Invite step counts accept notices. Wire: leader and member run this build together; the member PC needs the rebuilt `enter_chat.dll` 1.1.0.
Consent: user chose Y, socket notice only (no OCR), and approved the scope.
Result: simulated: notice → Y after the delay (scancode 0x15), skip when already in party / addressed to another roster name; DLL export loads and rejects a bad hwnd. Not run in game.

## 2026-10-22 — party: leader session id; member resets on a new leader run

Intent: every leader Start is a new party run. The member cannot tell from the socket alone whether the leader restarted (a reconnect looks the same), so the leader stamps a run id on every frame and the member starts its party state over when the id changes, then takes the new leader settings.
Shared: `websocket.party_orders.new_leader_session` / `leader_session` (8-hex id, made at leader Start in the run loop). `leader_decisions.publish_body` adds `session` to every leader frame (policy, rally, recovery, decision). `MemberOrders.ingest`: a new `session` drops gather / recovery / policy / arrived before the frame is read; `take_session_change()` reports it once. Controller `_reset_member_for_leader_session`: `PartyMemberManager.reset_for_new_leader_session()` (policy overlay off → own profile knobs, formation trail cleared), policy apply signature and ack records cleared, so the new policy is applied and confirmed (`policy_ack`) as on a fresh member start. At every Start both roles clear `member_orders` and `policy_acks`.
Affects: member party state only, on the first leader frame of a new run (first contact counts too). A member reconnect to the same leader run keeps everything. Rally walking toward an old gather point stops; the new run's rally replaces it. Join-map world nav in progress and solo decision state are not touched. Wire: leader and member must run this build together.
Consent: user asked that a newly started leader resets all member party logic to the leader's new settings.
Result: simulated: same-id resend keeps orders, a new id drops the old rally/arrived and applies the new policy (turret → moving). Monitor shows the session id on the Server (leader) / Connect (member) step. Not run in game.

## 2026-10-22 — enter_chat: probe the Interception keyboard slot (fixes `/초대` "failed: text")

Intent: Hangul in chat lines is sent only through Interception. `ec_ic_open` always used keyboard slot 1 (`interception_is_keyboard` is only a range check). On this PC the keyboard is slot 2 (autologin probe: `keyboard=2 mouse=12`); slot 1 returns 0 strokes, so every Hangul key of `/초대 번개공격` failed while `/`, space, and Enter went through fallbacks → `EC_E_TEXT` with no message.
Shared: `ec_keyboard.c ec_ic_open` now probes slots 1–10 with a key-UP of scancode 0x04 (no-op, same probe as `autologin/bot/win/interception.py`) and keeps the first slot that accepts; none → `EC_E_INTERCEPTION`. `EC_E_TEXT` now reports "N of M character(s) failed (keyboard slot X)".
Affects: every `send_chat_line` caller (party invite / leave). Mouse, login input, and decisions are unchanged.
Consent: user asked to find and fix why the party invite failed.
Result: live probe on this PC: slot 1 → 0, slot 2 → 1, slot 3 → 1. DLL rebuilt (BUILD_OK; the loaded copy was renamed to `bin/enter_chat.old.dll`, picked up after the bot restarts). Not run in game.

## 2026-10-22 — party start: invite only after the member confirms the policy (`policy_ack`); `/초대`; monitor workflow

Intent: the leader start runs in order: socket server → member sockets connect → `party_policy` sent → each member applies it (temporary overlay) and answers `policy_ack` → only then `/초대 <name>` for that roster name → rally → hunt. The in-game invite command is `/초대 <name>` (was `/파티 <name>`, which the game does not accept).
Shared: `invite.PartyInviter.tick(ready=…)` skips names that have not confirmed (no invite, no retry clock). `invite.LeaderInvites(policy_acked=…)` replaces the "all sockets or 20 s" shortcut; `POLICY_WAIT_S` is removed. `deliver_chat` turns an exception (e.g. missing `enter_chat.dll`) into a failed send instead of an uncaught invite-tick error, and posts typed / FAILED lines to the monitor. `websocket.party_orders`: `party_policy` now carries `policy_id` (hash of the knobs), new `policy_ack` frame, `PolicyAcks` / `policy_acks` (cleared by `reset_orders` and at Start). `comms.ingest.drain_leader_reports` books acks (a member that does not know its name yet sends `member`; booked to the only unconfirmed roster name). Member `_member_party_tick` acks every applied policy frame (leader resends every 5 s). `party_monitor_snapshot` adds `session.workflow` (leader 7 steps, member 6) and roster `policy_acked` / `invite_failed`.
Affects: leader party invites only. A member bot without this build never confirms, so it is never invited until it is updated (wire: leader and member must be deployed together). Rally, hunt, combat, HP, movement, and login are unchanged. Party monitor: left dashboard keeps its width (right column fixed ~420–640 px, wrapping badge rows), Workflow card on top, log split into leader messages (top) and member messages (bottom).
Consent: user asked for this workflow (socket → policy → member response → invite) and the `/초대` command; hard ACK (no timeout) as described.
Result: logs 03:48 and 04:03 showed `/파티` then `/초대` "typed" while the main log had `Party invite tick failed: enter_chat.dll not found` every 20 s — `Engine/analysis/enter_chat/bin` was never built after the move. Rebuilt with `build.bat` (BUILD_OK, DLL loads). Gate simulated: no invite before ack, invite right after, stale `policy_id` rejected, failed chat counts as failed. Monitor rendered offscreen. Not run in game.

## 2026-10-22 — teleporter door swap also moves the inside walk start

Intent: after the silver-knight teleporter lands nearer the other training-dungeon floor-1 door, the inside walk starts at that door's landing cell. The character then walks to the first patrol point. Standing still on `world nav wait land xy` after a successful mapId 4→25 entry ends.
Shared: `retarget_walk_from_after_gate`, called from `_rewrite_next_gate_from_live_pose`. The gate rewrite still picks the nearest `ground_enter`. `_start_walk` still waits until live xy is within 24 tiles of the walk's `from`. Combat, HP, login, and patrol order are unchanged.
Affects: world-nav trips whose teleporter step is followed by a gate and then a walk on the destination map. Training dungeon floor 1 is the case in `v77.log`: planned door `tmo:4:85` interior `(32738, 32805)`, live door `tmo:4:88` interior `(32808, 32810)`. A walk whose `from` is not the replaced gate's old interior is left as planned. The stored A* polyline for that one walk is dropped because it started at the other door; the hop still paths from the live cell to the same goal.
Consent: user agreed to this change after the v77 review.
Result: retarget checked on the v77 step pair (walk `from` moves to `(32808, 32810)`, a same-door plan stays put, a walk that does not start at the old interior stays put). Not run in game.

## 2026-10-21 — an attacked-me lock stays until that monster is dead

Intent: while the current sticky has attacked me and is still alive, a lower known level does not take the lock. When the lock is empty, the lowest known level is engaged, then held the same way. A sticky that has not attacked me still yields immediately. Who attacked first is the monster already on the lock; monsters that appear in the same scan are still ordered by known level. Unknown level still ranks after every known level. The previous target is not given up.
Shared: `prefer_attacked_me_sticky`. `attacked_me_rank` still orders an empty lock. `list_attacked_me_targets`, `rebind_sticky_target`, dungeon wall release, cursor reject, species-filter idle, bait, map change, and the exp-kill release stay.
Affects: farm engage, travel engage, and world-nav walk combat. Heal still waits while the living sticky is held, so a higher-level first attacker delays heal. Loot still waits. Field wall detour still holds the lock. A dungeon shot line that closes still drops the lock, and the next empty-lock choice is the lowest known level that can be shot.
Consent: user agreed after the review (keep the monster already being attacked until it dies; then take attacked-me monsters from weakest, each until death).
Result: the lower-level steal is gone. Not run in game.

## 2026-10-21 — silver knight teleporter lands at desert dungeon floor 1

Intent: a trip to training dungeon floor 1 uses the silver knight village teleporter the same way Gludin and Giran do. Talking scroll to 은기사 마을/텔레포터, click that NPC, land in front of a floor-1 door, then the existing cursor check enters. The long walk from the village to `(32950, 33502)` or `(32970, 33511)` is no longer the planned approach.
Shared: `teleport_silver` and `teleport_silver_ch` `destination_dungeon` is 25 (사막 던전 1층). The existing NPC-teleporter link, shop click, and gate rewrite are unchanged. Gludin (7) and Giran (53) are unchanged.
Affects: world nav into training dungeon floor 1, and any deeper desert floor whose world-nav stop is that entrance. A character already within 50 tiles of a floor-1 door still walks and clicks it. Combat, HP, and login are unchanged.
Consent: user (use the silver knight teleporter to reach desert dungeon floor 1, the same way the village teleporters reach Gludin and Giran).
Result: both behaviors now name map 25. That map's mainland doors are 130 and 126 tiles from the NPC `(33080, 33385)`, inside the 400-tile link. The old value 7779 is the PC clone and has no mainland door, so the planner scrolled to the village and walked. Not run in game.

## 2026-10-21 — path refusal logs P, M, and the closed tile together

Intent: one path refusal can be replayed from a single line. The line names the character tile, the monster tile the shot used, the closed tile, the live MapSubsystem id, and the loaded pack. The sampled tile list is debug only.
Shared: `attack_line_refusal_text` reads `attack_line_block` and `tiles_on_segment`. `describe_attackable_filter_skips` still returns the same summary and, when asked, fills that line. The dungeon sticky release uses the same line. `tiles_on_segment`, `diagonal_open`, `attack_line_clear`, and `can_engage_target` are unchanged.
Affects: screen-combat skip logs and a dungeon sticky release when the shot line is closed. Who is attacked, give-up, and blacklist stay the same. Field shots, travel, loot, and HP are unchanged.
Consent: user asked for this line before the next hunt, and said not to change the segment or diagonal rules until a real case shows a walk-blocked tile that the game still lets an arrow cross.
Result: the line is written. Not run in game.

## 2026-10-21 — dungeon attack skip logs the closed nav tile

Intent: when a straight shot is refused, the combat log names the first nav tile or fence that closed it. Who can be attacked stays the same.
Shared: `los_block_label` (same walk as `line_of_sight_clear`). `describe_attackable_filter_skips` appends `@block=(x,y)` or `@fence=(x,y,N|E)` on a path skip. The dungeon sticky release log `wall/fence — dungeon skip` includes that same label. `attack_line_clear` and `can_engage_target` still return the same yes or no.
Affects: dungeon screen-combat skip lines, and dropping a dungeon sticky because the shot line closed. Field shots, travel, loot, and HP are unchanged.
Consent: user agreed this scope (log the blocking tile only; do not change the engage decision).
Result: label added on both logs. Checked against a small grid: a black middle tile, two closed diagonal shoulders, and a north fence match the old clear/blocked result. Not run in game.

## 2026-10-21 — dungeon teleport with no heal or potion goes to the world tree

Intent: after one escape teleport off Talking Island and the mainland, HP still under the operator retreat percent, heal blocked by the existing MP floor, and no HP potion, start the existing Mother Tree trip instead of waiting for 95%. When HP is already above that retreat percent but still under 95%, and neither heal nor a potion can run, leave the retreat and resume the hunt. Heal or potion still fills to 95% everywhere. Scroll landings keep the 50% mother-tree check. A mother-tree trip still stands until 95%.
Shared: `maybe_mother_tree_before_passive_wait`, `retreat_exit_ready`, `begin_retreat(use_mother_tree=True)`, `finish_retreat`. `apply_hp_actions`, `apply_inplace_hp_support`, the one under-fire teleport, and potion sides are unchanged.
Affects: HP retreat after the escape teleport has landed, and any HP retreat that can no longer heal or drink. MP retreat, return retreat, and recharge at the tree stay on their current exits.
Consent: user agreed both gates (dungeon post-teleport mother tree; resume hunt above the retreat percent when heal and potion cannot run).
Result: both gates added. Not run in game.

## 2026-10-21 — a filtered species is attacked only while it is hitting me

Intent: a species the operator filter skips is never chosen, and an existing lock on it is dropped, unless its AttackAction targets the character this tick. One earlier hit is not enough. Allowed species still keep the attacked-me latch and finish-kill.
Shared: `sync_attacks_me_force_targets` (`attacking_me_now`), `species_filter_blocks_target`, `list_attacked_me_targets`, `rebind_sticky_target`, `_living_same_species`. `nearest_attackable` still skips every filtered species. Session target blacklist and give-up stay.
Affects: field and dungeon engage. A filtered monster that stops attacking is released the same tick, including a 2-tile rematch onto another of that species. A filtered monster that is attacking can still take the lock.
Consent: user asked to make sure a blacklist monster is not attacked when it is not attacking the character.
Result: current-tick flag added and idle filtered targets released. Not run in game.

## 2026-10-21 — dungeon fights a blacklisted species that is attacking

Intent: in a dungeon, a monster whose AttackAction targets the character is engaged even when the operator species filter would otherwise skip it. A blacklisted species that is not attacking stays off the normal attack list. Field self-defense was already this way.
Shared: `monster_hitting_me`, `list_attacked_me_targets`, `nearest_attacks_me_force`, `continue_sticky_combat`. `_dungeon_ignores_blacklisted_attacker` is gone. Session target blacklist (`blacklisted_target_ids`), give-up, dungeon line of sight, and the dungeon path cap stay. `nearest_attackable` still skips a blacklisted species that has not attacked.
Affects: dungeon hunt and patrol engage, and HP retreat while under attack. A blacklisted attacker can take the sticky lock and make `monster_hitting_me` true, so the one teleport-under-fire attempt can run. Field loot and field combat are unchanged.
Consent: user agreed this scope (dungeon attackers bypass the species blacklist; non-attackers stay filtered; session blacklist and give-up stay).
Result: filters removed. Not run in game.

## 2026-10-21 — body reader finds MyPlayer on the current entity list

Intent: ground clicks repeated the same screen point for a full second because the body slot read failed. The character walked past adena, so the in-range F4 never ran. Walk and stand class ids were already current. The player object was still looked up with the previous manager, actor list, and MyPlayer id.
Shared: `body_pose._find_my_player` / `read_action`. Manager, actor vft, and MyPlayer come from `entity_offsets.txt` (`0x16ED640`, `0x11E9430`, `0x11EC4C8`). The click-until-walk loop, loot approach, and F4 press are unchanged.
Affects: ground-click stop, travel reclick, and loot hop hold. A readable walk stops the repeat. A readable stand lets the next loot tick correct or press F4 once the tile is within one. Combat clicks, potions, and login do not read this slot.
Consent: user (update it so the approach-then-F4 workflow works).
Result: finder reads the live entity table. A live read returned walk `0x11EB7B8` and move command `0x11EBA50`. The approach-then-F4 path was not replayed in a hunt.

## 2026-10-21 — world nav reuses white-tile component ids

Intent: the first world-nav plan was flooding the mainland once per hub inside the decision tick, so the character stood for about 20 seconds after the startup buffs. The route itself was a scroll plus a 155-tile walk.
Shared: `WalkService.same_component`, `label_walk_components`, `shared_walk_service`, `WorldNavPlanner` (one shared walk service), `_warm_walk_components` on map load. White-tile 4-connected ids are stored beside `nav.png` as `walk_components/`. They are not `nav_prebuild/labels.npy`. Ground A* still runs on the chosen walk. The 80,000-cell optimistic flood remains only when those ids cannot be built.
Affects: the first world-nav plan after Start, and later plans in the same process. Live hops, combat, loot, and HP still use the fence-aware prebuild.
Consent: user (prepare the static map once and reuse it; do not change the route).
Result: closed yards and blocked corners match a finished flood. The logged plan no longer lands at 은기사 마을/여관. Exact white-tile ids allow 은기사 마을/허수아비 수련장, then a 106-tile walk (cost 116). The old 155-tile inn walk (cost 165, 27.8s) was a false wall left by the 80,000-cell flood. That 106-tile A* matches a fresh PNG grid. Map load reads the component files and the NPC catalog. After that the same plan is about 0.4s, and a repeat is about 0.2s. Not run in game.

## 2026-10-21 — body and command class RVAs follow bodyact

Intent: the live body reader was still on the 10.14 class numbers. bodyact on the current client reads stand as `VFT_BREATHACT` `0x11EB4D8`. Copy that table into the bot and the action monitors.
Shared: `body_pose.py` `BREATH_VFT` / `MOVE_VFTS` / `BODY` / `CMD`, `action_timeline.py`, `interact_watch.py`, `probe_my_anim.c` defaults, print_state attack-action default. Walk is still MovingAction, walk-back is still MovingBackAction. Decision branches are unchanged.
Affects: `body_is_moving`, ground-click stop, travel reclick, loot hop hold, action view labels.
Consent: user (if bodyact is the accurate one, bring its constants into the project).
Result: constants written. Shop, default, fixed-frame, npc-state, and zap-wand have no bodyact key, so those old numbers were dropped. Not run in game.

## 2026-10-21 — memory readers follow the 26.10.20.2001 registry

Intent: point the live readers at the current client using `D:\dist` registry RVAs. HP/MP/level come from CharacterData (`STAT_*`), world position from `PLAYER_X`/`PLAYER_Y`. The retired HUD block is not used. Dialog watch list stays the existing six windows.
Shared: offset files, `lc930` registry RVAs, `shop_listen.c` anchors, and the print_state/realtime_monitor vital decode. Decision, login, movement, combat, and potion code are unchanged.
Affects: every live memory read (player, entities, bag, hotbar, buffs, dialogs, shop).
Consent: user (update the readers so the project runs on the current game, using how dist reads the fields whose constants were not refreshed).
Result: constants written. `print_state.new.dll`, `realtime_monitor.new.dll`, and `shop_listen.new.dll` built; the live copies were locked, and the readers load the newer image. Not run in game.

## 2026-10-21 — ant cave floors 2–8 use their own mainland doors

Intent: ant cave floors 2 through 8 are entered at their own mainland doors, the same way talking island dungeon floor 1 is found and entered. Floor 9 stays without a mainland door.
Shared: `needs_floor_route` treats `ant_cave_dungeon_F2` through `F8` as direct field doors. World nav keeps the goal on that floor's map, skips interior ladders, and uses that floor's mainland ground-enter cells. `plan_floor_steps` is not used for these floors. Floor 1 and other dungeon stairs are unchanged.
Affects: a hunt set to ant cave floor 2, 3, 4, 5, 6, 7, or 8. The walk goes to that floor's mainland cell and the existing gate clicks it. Combat, HP, and login are unchanged.
Consent: user (connect floors 2–8 with the database entrance cells, the same way talking island dungeon floor 1 is entered, then verify each link from the mainland).
Result: from mainland `(33092, 33407)` with scroll and NPC teleports off, each floor plan is one field walk and that floor's own door. Floor 2 `(32912, 33223)` → `(32799, 32754)`, floor 3 `(32789, 33256)` → `(32776, 32730)`, floor 4 `(32845, 33292)` → `(32787, 32794)`, floor 5 `(32836, 33171)` → `(32795, 32744)`, floor 6 `(32796, 33189)` → `(32796, 32741)`, floor 7 `(32926, 33249)` → `(32800, 32781)`, floor 8 `(32757, 33205)` → `(32769, 32803)`. Not run in game.

## 2026-10-21 — route chaining stays inside dungeons

Intent: the route-cell chain belongs on dungeon walks only. Field travel keeps the straight-line extend and still waits for arrival on a bend.
Shared: `emit_travel_hop`. A dungeon hop calls `_chain_route_click`. A field hop calls `_straight_extend_waypoint` when the body is walking and two tiles from the click. Loot, search, combat, HP, and login are unchanged.
Affects: dungeon patrol and dungeon floor walks. Field travel, farm entry, and retreat use the straight-line extend again.
Consent: user (this direction, and only inside a dungeon).
Result: implemented. The route-click check still passes. Not run in game.

## 2026-10-21 — travel chains the next clear route cell while walking

Intent: dungeon walks stopped at every bend, and stopped for up to 5 seconds where a corridor narrows, because the next click was issued only on a straight line or after the current click had finished.
Shared: `emit_travel_hop` and `_next_route_click`. While a hop is active the live tile clicks the farthest route cell whose client walk is still clear, including a turn. A closed door stays the click. An open door still clicks the tile just past the doorway. The click does not pass the goal. A sidestep off the route stays until a route cell is clear again. The 5 second unstick remains only when no route cell and no sidestep exist. Hop caps stay dungeon 3 and field 5. Loot, search, combat, HP, and login are unchanged.
Affects: field travel, farm entry, retreat, and dungeon patrol. A straight hall still walks in hops of at most that cap. A bend clicks the next clear cell as soon as the live tile can walk it. A narrow bend shortens to 2 or 1 tile instead of waiting.
Consent: user (chain the next clear route cell from the live tile, including turns, and do not wait out the 5 second unstick on a wall).
Result: implemented. A local route-click check passed for a straight hop, a corner that clips, a one-tile shorten, a body on the path, and the goal limit. Not run in game.

## 2026-10-21 — training dungeon return walks back through each yard

Intent: from floor 4 the way to 은기사 마을 leaves floor 3 at `(32806, 32814)` onto `(32880, 33512)`, enters floor 2 at `(32910, 33503)`, leaves floor 2 at `(32802, 32816)` onto `(32927, 33516)`, enters floor 1 at `(32950, 33502)`, and leaves floor 1 at `(32809, 32810)` onto `(32970, 33512)`, then walks to the village.
Shared: five `floor` rows in `floors_entrances.txt`, each using that direction's own cell. `plan_floor_steps` still stops on the goal floor. World nav skips a same-map walk when the nav grid's walk ends before the other cell. A mainland floor walk that is still open after 2000 cells is not a door yard.
Affects: a walk from floor 4 to a mainland point, and a floor route from floor 4 down to floor 1. Floor 2, 3, and 4 hunts that start on floor 1 still use the forward doors. A talking scroll can still skip the walk. Combat, HP, and login are unchanged.
Consent: user (leave floor 3 into its yard, enter floor 2, leave by the other exit, enter floor 1, leave by the field exit, and walk to the village, using the database cells the same way as the earlier doors).
Result: with the scroll off, the plan is stair to floor 3, `(32806, 32814)` → `(32880, 33512)`, walk to `(32910, 33503)` → floor 2 `(32733, 32813)`, walk to `(32802, 32816)` → `(32927, 33516)`, walk to `(32950, 33502)` → floor 1 `(32738, 32805)`, walk to `(32809, 32810)` → `(32970, 33512)`, then 126 tiles to `(33092, 33407)`. The forward floor 4 route is unchanged. Not run in game.

## 2026-10-21 — world-tree return waits until mapId and xy match

Intent: after Teleport to Mother, the return plan was sometimes armed while absolute xy was already the world tree and MapSubsystem mapId was still the hunt floor. That sample is same-map, so the planner walked, and a dungeon id was treated as already on the floor.
Shared: `arm_world_nav` defers while xy is outside that mapId's nav image, and on `post_retreat` while mapId is still the departure dungeon floor and xy jumped more than 40 tiles. `_dungeon_live_pack` does not report the floor when xy is outside its image. The first Teleport to Mother press in a retreat stores the departure pose; a recast does not replace it. `finish_retreat` and the planner `same_map` rule are unchanged.
Affects: the world-nav arm after a mother-tree retreat. A shop return or hunt re-entry whose xy is outside the live map image waits the same way. Mainland hunts share mapId 4 with the tree, so they still plan on that tick. Combat, potions, login, and an in-progress walk are unchanged.
Consent: user (defer the return until mapId and xy name the same map).
Result: implemented. A local image-bounds check passed for mainland versus a dungeon floor. Not run in game.

## 2026-10-21 — training dungeon floors stay in one line

Intent: floor 1's courtyard `(32950, 33503)` cannot walk straight into the floor 3 door. The route goes through floor 2, out to `(32910, 33504)`, then into floor 3 `(32807, 32813)`, then the existing stair to floor 4.
Shared: `dungeon_floor_route` now keeps mainland steps on one world tile, and may enter the mainland again when the next yard is a different place. `plan_floor_steps` callers are unchanged. Door rows already in `floors_entrances.txt` were not edited.
Affects: training dungeon floor 3 and 4 routes. A floor 2 hunt still stops at `(32803, 32815)`. Other dungeon stairs are one tile per cell already. Combat, HP, and login are unchanged.
Consent: user (the linked doors are one line, so the first courtyard must not enter floor 3 directly).
Result: from floor 1 the floor 4 route is courtyard `(32927, 33515)` → floor 2 `(32803, 32815)` → `(32732, 32814)` → mainland `(32910, 33504)` → `(32880, 33511)` → floor 3 → `(32723, 32742)` → floor 4 `(32799, 32798)`. The direct walk from `(32950, 33503)` to `(32880, 33511)` has no path. Not run in game.

## 2026-10-21 — routine timer counts only inside the hunt zone

Intent: the left routine countdown starts when the character enters the hunt zone, pauses outside that zone and while the project is paused, and returns to the full duration on Stop. Reaching the zone center must not wipe time already counted from the edge.
Shared: `RoutineCursor` no longer starts in `from_entries`, `advance`, or `mark_arrived`. `sample_routine_zone_clock` opens and closes it. `_resume_stay_clocks` no longer resumes the row clock. `_routine_clock_from_board` shows "Moving" until the battle row is inside its zone.
Affects: the routine row duration. Travel, time outside the selected rectangles, and pause do not consume those minutes. A field revive keeps the saved seconds instead of starting at zero. Dungeon retreat still holds the clock, and time off the hunt floor is not counted. Break rows still count while the project is deciding, including the walk to a rest spot. The per-area farm stay clock is unchanged. Combat, movement, HP, and login are unchanged.
Consent: user (proceed with the timer rules from the prior analysis).
Result: implemented. A local sampler check passed. Not run in game.

## 2026-10-21 — second courtyard door enters training dungeon floor 3

Intent: from mainland `(32910, 33504)` the character walks to `(32880, 33511)` and the existing cursor check enters training dungeon floor 3 `(32807, 32813)`.
Shared: `plan_floor_steps`, `_plan_dungeon_floor_session`, `_drive_dungeon_floor_walk`, and `_drive_dungeon_floor_transition` are unchanged. One `floor` row was added in `floors_entrances.txt`.
Affects: floor routes that use this door. A start on `(32910, 33504)` walks to the door and gates into floor 3. A floor-3 hunt that begins on floor 1 walks the coarse mainland grid from the first courtyard `(32950, 33503)` straight to this same door. Floor 4 then continues on the existing floor-3 stair `(32723, 32742)`. The floor-2 arrival route is unchanged. Combat, HP, and login are unchanged.
Consent: user (walk from `(32910, 33504)` to `(32880, 33511)` and enter floor 3).
Result: the router emits that walk and a floor gate `(32880, 33511)` → `(32807, 32813)`. Mainland walk on the coarse grid is 8 cells. Not run in game.

## 2026-10-21 — training dungeon floor 2 other exit to the mainland

Intent: floor 2 `(32732, 32814)` is a floor gate out to mainland `(32910, 33504)`. The character walks to that cell and the existing cursor check clicks it.
Shared: `plan_floor_steps`, `_plan_dungeon_floor_session`, `_drive_dungeon_floor_walk`, and `_drive_dungeon_floor_transition` are unchanged. One `floor` row was added in `floors_entrances.txt`.
Affects: a floor route that must leave floor 2 through this door. The floor-1 to floor-2 arrival route is unchanged and still stops at `(32803, 32815)`. Combat, HP, and login are unchanged.
Consent: user (connect this exit the same way: walk to the cell, cursor check, click).
Result: from floor 2 `(32803, 32815)` the route is one walk to `(32732, 32814)` and a floor gate to mainland `(32910, 33504)`. The landing nav cell is walkable. Not run in game.

## 2026-10-21 — courtyard door enters training dungeon floor 2

Intent: the courtyard cell `(32927, 33515)` is a floor gate into training dungeon floor 2 `(32803, 32815)`. A character who has left floor 1 into the courtyard walks to that door and the existing cursor check enters floor 2.
Shared: `plan_floor_steps`, `_plan_dungeon_floor_session`, `_drive_dungeon_floor_walk`, and `_drive_dungeon_floor_transition` are unchanged. One `floor` row was added in `floors_entrances.txt`.
Affects: a floor-2 hunt that is already inside this dungeon. The planned steps are a walk on floor 1, the courtyard gate, a walk across the courtyard, then the floor-2 gate. Floor 3 and 4 still have no route from floor 1. Floor 1 hunting, combat, HP, and login are unchanged.
Consent: user (connect the courtyard to floor 2 the same way as the floor-1 courtyard gate).
Result: from floor 1 `(32808, 32810)` the route is walk `(98, 166)`, gate `(32738, 32806)` → mainland `(32950, 33503)`, walk mainland nav `(119, 346)`, gate `(32927, 33515)` → floor 2 `(32803, 32815)`. Both gates are floor gates. A route to floor 3 still fails. Not run in game.

## 2026-10-21 — training dungeon floor 1 exits into the courtyard

Intent: on training dungeon floor 1, the exit `(32738, 32806)` is a floor gate into the walled courtyard `(32950, 33503)`. The character walks to that cell and the existing cursor check uses it, the same way a stair is used.
Shared: `plan_floor_steps`, `_plan_dungeon_floor_session`, `_drive_dungeon_floor_walk`, and `_drive_dungeon_floor_transition` are unchanged. The new row is a `floor` link in `floors_entrances.txt`. Mainland `meta.yaml` now has `raw_map: "4"` so that list's name `아덴 대륙` resolves to the mainland pack.
Affects: floor-route search that starts on training dungeon floor 1. Floor 1 hunting, mainland travel, combat, HP, and login are unchanged. The courtyard's floor 2 door is not part of this link.
Consent: user (yes to this floor-1 courtyard gate only).
Result: the router sees `사막 던전 1층 (32738, 32806)` → `아덴 대륙 (32950, 33503)` as a floor gate. The walk from the field landing `(32808, 32810)` to that exit is 71 tiles. A route onward to floor 2 still does not exist, so a floor-2 hunt does not leave through this door. Not run in game.

## 2026-10-20 — exp rise releases sticky attack and the aim pixel

Intent: when level or exp rises while a monster is stuck as the current target, drop that sticky before rebind and do not click the last attack pixel again. The 30px cursor nudge is unchanged.
Shared: `sample_kill_progress` / `_release_sticky_for_kill` (`EXP_KILL_RELEASE_ENABLED` on). `excluded_target_ids` already hides that id until it leaves the monster list. `ActionExecutor._drop_killed_attack_aim` clears `_attack_aim_lock` for that id. `rebind_sticky_target` and `attack_click_search` are not reordered.
Affects: farm and dungeon engage, including `finish_kill`. Loot, the next monster, and search run on that tick only after the sticky attack no longer owns it. A kill that grants no exp still waits until the row leaves the list. An exp gain from something other than this kill also releases a held sticky.
Consent: user (release sticky on exp rise and invalidate the aim lock; do not add a cursor nudge).
Result: implemented. Not run in game.

## 2026-10-20 — Windawood floor 2 door, inner castle gate, ice floor 2 stair

Intent: Windawood Castle Dungeon 2F is entered at its own mainland door `(32551, 33478)`, not by climbing from floor 1. The inner castle is a gate from floor 1 `(32811, 32722)` to `(32742, 32789)`. Ice Queen 2F stays on the floor-1 stair `(32726, 32861)` → `(32755, 32870)`.
Shared: `needs_floor_route` treats only `windawood_castle_dungeon_F2` as its own field door. Edges `tmo:23:1` and `tmo:29:1` are live `floor_ladder` gates, so the existing cursor check runs them. Desert floors and other passages stay as they were.
Affects: world nav into these three maps, then patrol after arrival. Combat, HP, and login are unchanged.
Consent: user (connect these three first; do not also switch the desert floors).
Result: floor-2 no longer redirects to floor 1. Inside floor 1, the walk to the inner-castle gate is 139 tiles. Ice floor 2 plans as one walk plus a gate-compatible stair. A plan from Woodbec to either Windawood field door still fails A*: those door tiles sit in a 303-tile pocket walled off from the mainland field. Not run in game.

## 2026-10-20 — a closed door on the path is opened like an entrance

Intent: when this hop must cross a closed door, the cursor goes to that door's memory tile and circles the way a dungeon entrance is found. The first exact door cursor is clicked once.
Shared: `closed_door_before_click` and the travel click in `_search`. `sweep_click_closed_door` uses the entrance ring sizes and step. Open-door retarget, `not_permitted` walls, and the single door click stay. The entrance ESC, 20s retry, and map wait are not used.
Affects: travel, patrol, and loot-approach hops whose guide reaches a `close` door. Combat, HP, and login clicks are unchanged. A missed door cursor still uses the existing ground hop.
Consent: user (use the entrance cursor sweep on a closed door the path must cross, if that adds no other behavior).
Result: implemented. Guide check passed. Not run in game.

## 2026-10-20 — revert post-upload travel, attack aim, and cursor dump

Intent: keep only the income-bar runtime label. The uncommitted travel, attack re-aim, and cursor-reject dump from after `2f76607` go back to that commit.
Shared: `emit_travel_hop`, `retry_travel_hop_from_fresh` (removed), `attack_click_search`, `KnightCombatStrategy.attack`, `note_cursor_probe`. The income bar in `live_income_bar.py` stays.
Affects: world nav, farm entry, retreat, dungeon walks, attack clicks, and cursor probes. Those paths match the uploaded build again. `사슬 갑옷` is back on the keep list.
Consent: user (restore every post-upload change except the runtime next to gained adena).
Result: working tree restored to `2f76607` except `UI/ui_qt/shell/live_income_bar.py`. Not run in game.

## 2026-10-21 — party invites in one module (`_06_party/invite.py`)

Request: "파티초대를 한개의 모듈로 정리하라". Refactor only, behaviour unchanged.

`setup.py` (PartyInviter, roster names, leave check) and `chat_commands.py` (`/파티 `, `파티탈퇴`) are merged into `invite.py` and deleted. The invite glue that lived in `bot_controller` (`_send_party_chat`, `_party_ws_clients`, `_INVITE_UNSAFE_ACTIONS`, `POLICY_BEFORE_INVITE_WAIT_S`, the per-tick policy / socket / action checks, the "Party setup:" log) moved into `invite.LeaderInvites` (`start`, `tick`, `info`, `deadline`) with `deliver_chat`, `action_allows_chat`, `POLICY_WAIT_S`, `UNSAFE_ACTIONS`. The controller keeps the profile gate + party probe in `_run_leader_party_setup`, a one-line `_leader_invite_tick`, and holds `self._party_invites` (snapshot and rally deadline read it). The "Party setup:" log line now lists the names actually invited (self skipped).

Result: party suites 221 passing (2 skipped); new `LeaderInvitesTests`.

## 2026-10-21 — party start: 15 min invite + rally window, /파티 every 20 s, exclusions; member socket error text

Consent: user ("초대를 15 분시간을 크게 잡고 20초간격으로 초대를 보내 … 15분후에도 연결되지 않는 성원에 대해서는 배제하고 그 상태를 파티 모니터에 보여주어야 한다", "15분안에 파티초대 및 집결을 완결하고 그 후에는 사냥터에로의 진입"); AskQuestion: invites run in parallel with travel; error shown in status line + log + monitor; go = yes.

**Invites** (`_06_party/setup.PartyInviter`, replaces blocking `configure_party_from_roster`). Setup once: publish policy, `/탈퇴` if in someone else's party, arm the inviter. Each tick (`bot_controller._leader_invite_tick`): one `/파티 <name>` at most, every 20 s per roster name not in party memory; stops for a name once it is listed. First invites wait for all member sockets or 20 s (policy before invite, no longer blocking). A tick is skipped when the previous action was `shop_run` / `shop_stop` / `gate` / `teleport` / `use_talking_scroll` / `return_to_mother_tree` / `respawn` / `dismiss_level_up` (chat must not hit an NPC dialog or a teleport). Window 15 min from setup → names still missing are excluded; a late join clears the exclusion.

**Rally** (`LeaderStartRally.begin(deadline=)`): the same deadline. At the deadline the rally ends in any state (await_plan / hold_at / waiting), records `left_behind`, and the leader goes on to the hunt. Without a deadline the old 15 min from wait start still applies (tests).

**Monitor**: leader session `phase` {forming | rally | hunting, remaining_s, excluded, not_arrived}; roster rows add invites / invite age / state (pending · invited · joined · ready · not_arrived · excluded). Dashboard: PHASE badge, INVITE `n/m JOINED|FORMED|EXPIRED`, roster Invites + Status columns.

**Member socket error**: `party_ws_unreachable` text (EN/KO/ZH) in the header status; `start_error` in the party monitor note (red); log line unchanged.

Shared: `set_party_hold` path unchanged (rally waiting only). Not touched: member logic, turret / moving, combat, HP. Side effects: while the leader travels, invite lines are typed between steps; a teleport/NPC step skips that tick's invite.

Left as is (by request): member invite accept (not automated), member `recovery` handling, explicit party end / leave.

Result: implemented. Tests: `test_party_invite_setup` rewritten (inviter interval, join stop, window/exclusion, late join, unsafe action skip, leave first), `test_party_rally` shared-deadline tests; party suites 216 passing (2 skipped).

## 2026-10-21 — moving mode: member single-file trail in narrow areas; leader waits for lagging members

Consent: user — member "yes" (moving mode, NARROW → trail tile); leader "반수이상의 성원들이 뒤떨어지면 잠간기다리라, 6타일은 너무 작이 30 타일정도로 하라 그리고 파티장 대면부에서 타일개수를 설정하게 하라".

**Tactics cleanup** — `tactics/teleport_sync.py` and `tactics/stagger.py` deleted; `focus_fire` stays library-only. New `_06_party/formation.py` composes `terrain_kind` + `trail`.

**Member** (`manager._formation_trail_tile`): moving mode only (`leader_mode != turret`), leader on the same map. `MemberFormation` records the leader tile each tick and reads the area (re-read every 2 leader tiles, hysteresis). While the leader walks (not stopped, not farming) and the area is NARROW and the member has a roster seat, the FOLLOW goal is the trail tile `spacing 2 × (seat+1)` behind the leader (sticky, `stand_reason=follow_trail`) instead of the formation slot. OPEN / no seat / no reading → existing travel slot. Not touched: turret seat, settle stand (leader stopped), combat, loot, join_map. Status: `runtime.formation`.

**Leader** (`bot_controller._leader_line_hold` → `set_party_hold`): party on + role leader + `party_leader_mode == moving` + start rally not waiting. `LeaderLineWatch` records the leader's `world_origin`; followers come from party memory (`world.last_party`, non-leader rows; other map = behind; no tile = ignored). Lag = max(Chebyshev, steps behind on the leader trail). When half or more known members lag more than `party_lag_tiles` (default 30, 5–100) the leader holds via the existing `party.hold_ground` (counterattack in reach, else IDLE) for at most 8 s, then walks on for 6 s before it may wait again. Any terrain. Shared path: `set_party_hold` (same flag as the start rally; rally takes priority).

**Setting** — `party_lag_tiles` (profile, task_runtime, schedule, settings bag `party.lag_tiles`), Party tab leader card spin box "뒤처짐 대기 (타일)" (enabled in Moving), i18n EN/KO/ZH. Monitor: leader MODE badge `MOVING ⏸` + "Line wait" metric.

Side effects: a member that disconnects from party memory is ignored; a member on another map (e.g. shopping) counts as behind and causes 8 s waits every 14 s until it returns. While waiting the leader does not search for new mobs.

Result: implemented. Tests: `test_party_formation` (majority rule, corner lag by trail steps, other map, setting, timeout/cooldown, party rows, member trail in manager); party suites 207 passing (2 skipped).

## 2026-10-21 — turret: leader anchor, member CLOSE_IN out of yard, radial seats; member loot/assist import fix

Consent: user ("터렛에서 대상이 야드 밖이면 HOLD → CLOSE_IN and return naturally", "터렛모드에서 리더가 중심이 돼서 사냥을 조직한다. 선택된 사냥지점을 떠나지 않고 거의 그 자리에서 사냥한다. 1-2 타일의 움직임은 감수한다", "tactics", "구현할것은 구현하고 수정할것은 수정하라").

**Leader turret** (new `app._04_decision.behaviors.party_turret`). Session arms it each tick via `set_party_turret` only when party on + role leader + `party_leader_mode == turret` + start rally not waiting. Anchor = first tile inside the active farm (or first hunt tile when no farm rect), stored per live mapId; dropped if >40 tiles away.
- `party.turret_leash` (island + dungeon columns, right before `farm.engage`): monsters farther than leash 2 (+ reach for ranged) from the anchor and items farther than 2 are written to scratch; `excluded_target_ids` now unions them (empty unless turret is armed). Sticky target / item outside the zone is released. Leader >3 tiles from the anchor walks back unless its current target is within reach.
- `party.turret_idle` (right after `farm.engage`): nothing to do → walk back (>1 tile) or IDLE on the anchor; `farm.enter` / `farm.search` / `dungeon.patrol` do not run.
- Shared function touched: `excluded_target_ids` (one extra set, empty for solo / moving). Not touched: `farm_loot_or_combat`, survival, retreat, shop, world nav (all run before the turret steps).

**Member turret** (`decide_policy`, `manager`): target outside the yard → CLOSE_IN (unclamped) instead of HOLD. Yard rejoin is skipped while a fight is in progress (`assist_sticky` = same target as last tick, or target inside the yard); after it ends the member walks back. A member already outside the yard ignores a new outside-yard target and rejoins first.

**Tactics** — `tactics.radial` wired: new `turret_seat.py`. Policy carries roster order → `seat_index_for_name` → `PartyMemberConfig.seat_index`. In turret, a member with no target walks to its ring seat (`fan_slots` full ring, radius ≤2 inside the yard, `resolve_slot` for blocked / no-sight tiles) — reason `turret_seat`; the seat also replaces the random settle stand as the FOLLOW goal. Moving mode unchanged. Other tactics (trail, stagger, teleport_sync, focus_fire) still library-only.

**Bug fix** — `_06_party/loot.py` and `assist.py` imported the removed `GIVE_UP_COOLDOWN_TICKS` and called `excluded_target_ids(bb, ticks)`. The ImportError was swallowed: member primary hold-loot (`try_party_hold_loot`) never ran and assist / solo-farm skip sets were always empty. Now `excluded_target_ids(bb)`.

Side effects: leader in turret ignores far ranged attackers it cannot reach from the zone (members still fight them inside their leash); a farm with no mobs near the anchor means the leader waits instead of searching. Monitor: leader MODE badge `TURRET ⚓` + "Turret anchor" metric.

Result: implemented. Tests: new `test_party_turret` (anchor, zone exclusions, leash, idle, per-map anchor, assist skip regression) + policy/seat tests; party suites 194 passing (2 skipped without LC.exe). Full discover: 15 pre-existing errors unrelated (missing `game_geom`/`gameflow`/`pipeline` modules, stale `GIVE_UP_COOLDOWN_TICKS` / `on_dungeon_return_town` imports in tests, account store env).

## 2026-10-21 — member party: require leader socket at Start, watch + reconnect during party

Consent: user (wait 60s at Start; while disconnected keep farming on the last policy; implement).

Intent: a member with party enabled must not run without the leader's socket. During the party a drop must reconnect.

Start (`BotController._worker` → `_start_party_client`): member + party on → start client, `PartyComms.wait_member_connected(MEMBER_CONNECT_WAIT_S=60, stopped=stop_event)`. No client (empty Leader IP) or timeout → log + party event, `stop(reason="party_ws_unreachable")`, bot loop never runs (no login / movement). Leader and solo bots unaffected. User Stop during the wait aborts it.

During party (`_member_party_tick`, read phase): `PartyComms.watch_member` logs drop #n / reconnected after Ns, and restarts the client IO thread if it died (throttled 5s). `PartyClient` already retries every 2s. Behaviour while down is unchanged: follow/fight via in-game memory + last policy overlay.

Monitor: socket snapshot adds `drops` / `restarts` / `down_s` and state `reconnecting`; dashboard WS badge shows `RECONNECTING #n`.

Side effects: member started before the leader now stops after 60s; wrong Leader IP stops the member instead of farming alone. Watch only runs inside the in-game loop (during login the client still auto-retries).

Result: implemented. Tests: `test_party_member_link` (new) + party suites, 140 run, all passing (2 skipped without LC.exe). Fixed `test_party_invite_setup` fixture missing `_party_comms` (broken by the earlier policy-before-invite change). Live check against a local `PartyServerWatchdog`: gate False with no server, True once up; stop server → drop #1 → reconnected ~1s after restart.

## 2026-10-21 — split farming method: leader turret / moving, member party / solo

Consent: user ("team leader option: turret and moving (이동). Member side: party and solo. Fix related codes").

Intent: the leader picks `leader_mode` (`turret` default, `moving`) and sends it in `party_policy`. Each member picks its own `farm_mode` (`party` default, `solo`), which the leader no longer overrides. `PartyMemberConfig.turret_farm` now reads `leader_mode == "turret"`, so the yard rules apply to both party and solo members while the leader is in turret mode (before: solo skipped the yard). In moving mode there is no yard: party = assist + close-in, solo = own target, as before.

Shared: `decide_policy` combat branch merged (yard rejoin → assist / close-in / hold-out-of-yard). Reasons kept: `assist`, `close_in`, `solo_farm`, `solo_close_in`, with a `turret_` prefix in turret mode. Profile: `party_farm_mode` (party|solo, default party; old `turret` → party), new `party_leader_mode` (turret|moving). Party tab: leader card = Turret / Moving combo; member panel = Party / Solo combo. Dashboard: MODE + FARM badges.

Not changed: the leader's own hunt routine is the same in turret and moving (it only steers members). A leader "hold the spot" behaviour for turret would need a separate change.

Result: implemented. Party policy / member / monitor tests: 84 run, all passing (2 skipped without LC.exe).

## 2026-10-21 — follow / stop / assist are member settings

Consent: user ("따라가기 / 정지 / 어시스트 — these for member bot").

Intent: movement distances are tuned per member bot (class range differs), so the leader no longer sends them. `policy_message` drops `follow_tiles` / `stop_tiles` / `approach_tiles` / `assist_leash_tiles`. `merge_leader_policy` always keeps the member's own values, even if an older leader still sends them. The Party tab moves the three spin boxes from the leader card to the member panel.

Leader policy now carries farm method, loot mode / priority, roster seats + loot, and party size (yard).

Result: implemented. `test_party_farm_policy.py` has 10 tests, all passing.

## 2026-10-21 — party policy sent before invite; member overlay is temporary

Consent: user ("send the profile settings to each member before the party invite… temporarily merge… solo must use origin profile… implement this cleanly").

Intent: the leader pushes `party_policy` before the first `/파티`, waiting up to 20 s (`POLICY_BEFORE_INVITE_WAIT_S`) for roster members to connect over WebSocket and re-sending to each newcomer. The periodic 5 s resend still covers late members. On the member, the policy is an in-memory overlay: `PartyMemberManager.base_config` keeps the member's own knobs, `apply_leader_policy` merges on top, `clear_leader_policy` restores them. Leader identity and member-only knobs (potion ratio, defend) survive. The overlay is re-applied when the policy or the member's own name changes.

Shared: `_run_leader_party_setup` (new pre-invite step), `_send_party_policy_before_invite`, `_apply_member_party_policy`, `PartyMemberConfig.with_knobs_from`. The profile is never written, so a solo run (party off, no `party_brain`) always uses the member's original profile.

Side effects to watch: leader invites can start up to 20 s later when members are not connected.

Result: implemented. `test_party_farm_policy.py` has 10 tests, all passing. Not yet run in game.

## 2026-10-21 — turret farm default + leader party_policy

Consent: user ("implement… base farming mode… main setting… team leader… roster roles… looting solo/responsible… farming method global").

Intent: member base farm is turret (yard assist around the leader). Leader owns global farm method, loot mode, follow knobs, and roster seats (mage default; shopkeeper optional). Leader broadcasts `party_policy`; members `merge_leader_policy` (per-name seat + loot).

Shared: `farm_yard.py`, `PartyMemberConfig.merge_leader_policy`, `policy` turret branch, `party_orders.policy_message` / `MemberOrders.policy`, `PartyComms.publish_policy`, `BotController` publish/apply. UI Party tab: farm/loot on leader; roster Role+Loot; member WS-only. Profile/task_runtime default `party_farm_mode=turret`.

Affects: party member decide (turret yard), leader ticks (policy publish). Solo hunt / HP / login unchanged.

Result: implemented. `Others/tests/test_party_farm_policy.py` added.

## 2026-10-20 — party `comms/` facade (wire unchanged)

Intent: all party WebSocket I/O goes through `app._06_party.comms` so session and behaviour modules do not import `websocket.party_orders` / leader ticks directly.
Shared: new `comms/` (`PartyComms`, `orders`, `link`, `publish`, `ingest`, `status`). `leader_rally` / `manager` import `comms.orders`. `BotController` socket lifecycle and leader/member ticks use `PartyComms`. JSON envelope and body `type`s unchanged. Invite chat still `_05_action.chat` (not socket).
Affects: party session glue only. Combat, HP, login, solo decide columns unchanged.
Consent: user ("go on" after README modularization plan).
Result: implemented. README §4 updated. Party unit tests to verify.

## 2026-10-20 — invite retry: 30 s × up to 3 after each failed `/파티`

Intent: when an invite line fails, wait 30 s and try again, up to 3 retries (`INVITE_RETRIES` / `INVITE_RETRY_S`), then move to the next roster name.
Shared: `configure_party_from_roster` only. Leave still has no retry (failed leave stops invites).
Consent: user ("실패하면 30초 간격으로 최대 3번까지 다시 시도").
Result: implemented. Invite unit tests cover all-fail retries and success on the 3rd try.

## 2026-10-20 — invite all names; rally wait 15 min; elf hold = solo click range

Intent: three corrections to the party leader start path.
1. Invite: a failed `/파티` line no longer stops the rest — every roster name is attempted; only a failed `파티탈퇴` still stops (cannot invite as non-leader).
2. Rally wait: if not everyone has arrived after 15 minutes, the leader skips the rally and continues to the hunt (`LeaderStartRally.WAIT_TIMEOUT_S`).
3. Hold-ground elf reach: use solo `ATTACK_CLICK_TILES` (default 8) instead of a hardcoded 6.
Shared: `configure_party_from_roster`, `LeaderStartRally.update` / `_enter_waiting`, `hold_ground_reach`. Combat/HP/login paths otherwise unchanged.
Consent: user ("i have to send all", "time out is 15 mins", elf = solo range).
Result: implemented. Invite / rally / hold-ground unit tests updated.

## 2026-10-20 — party rally wait: hold ground and hit back only at attackers

Intent: while the leader waits for the roster (start rally, both the no-travel wait and the wait on the teleport landing), potions keep working and the leader fights only monsters attacking it, from its current tile. No chase, no loot, no wall detour or unstick, no new non-attacker targets.
New step `party.hold_ground` (`app._04_decision.behaviors.hold_ground`), placed right after `survival.return_vitals` in the WORLD_NAV, FARMING_ISLAND, FARMING_DUNGEON and TRAVELING columns. It is a no-op unless blackboard scratch `party_hold_ground` is set. When set: ATTACK the nearest monster from `nearest_attacks_me_force` if it is within reach (melee 1 tile, elf 6, mage in spell mode `MAGE_SPELL_RANGE`) and `can_engage_target` holds; otherwise drop the target and emit IDLE "party rally wait members". Steps after it (shop trip, return-on-idle, routine duration, nav, spells, farm, world-nav drive) do not run during the wait.
Shared: reuses `nearest_attacks_me_force`, `can_engage_target`, `begin_engage`, `note_attack_attempt`, `clear_loot_hop` read-only/as-is; `continue_or_start_combat`, `farm_loot_or_combat`, `try_combat_wall_detour`, `try_combat_blocked_unstick`, HP functions are not changed. `bot_controller` sets the flag every tick from `LeaderStartRally.waiting` (leader only) and freezes the routine/farm clocks during the wait; the old gate that skipped decide during the no-travel wait is removed, so decide (and survival) now runs then. `LeaderStartRally.waiting_before_route` removed.
Affects: party leader during the start rally only. Solo and members: the flag is never set, so the new step does nothing.
Side effects to watch: an attacker beyond reach (ranged monster for a melee leader) is not fought and keeps hitting; survival (potion, emergency teleport, return on vitals) still wins and can move the leader off the rally tile. Elf reach follows solo `ATTACK_CLICK_TILES`. Survival handoffs to RETREATING/SHOPPING leave the hold columns (those columns have no hold step).
Consent: user (fight = new guard "팀장을 공격하는 몬스터만 제자리에서 반격, 추격·루팅 없음"; start wait = same as landing wait).
Result: implemented. `Others/tests/test_party_hold_ground.py` and `test_party_rally.py` pass. Not run in game.

## 2026-10-20 — party start rally on the last teleport landing (replaces the town rally and NPC-click wait)

Intent: on the first hunt trip after party start, the leader gathers the roster where the route needs it.
- No teleport on the way (already on the hunt map / in the target dungeon, or a walk-only world-nav plan): send the leader's tile (`rally` stage `start`) and wait there.
- Teleport on the way (NPC teleporter or talking scroll): when the plan exists, send the planned landing of the last teleport (stage `planned`), travel without waiting at the NPC, then send the real landing tile (stage `landed`) and wait before the next step.
Waits for every roster member, or 15 minutes (see later entry). Later trips (recovery return, schedule change) do not rally.
Shared: `websocket.party_orders` — one `rally` message with `stage`; `hunt_move`, `town_rally`, `npc_click_allowed`, `note_hunt_plan` removed. New `app._06_party.leader_rally.LeaderStartRally`. `WorldNavHooks.allow_npc_teleport` replaced by `hold_at_step(step_i, pose)`, checked in the `ready` phase before each step (solo: unset, no effect). Member reports tag `order` as `rally:<stage>`.
Affects: party leader first hunt trip, party member gather. Solo world nav, combat, HP, retreat, loot, and login are unchanged.
While holding inside world nav the WORLD_NAV survival steps (HP, emergency) still run; combat does not (world-nav combat runs only in the walk phase). The no-travel start wait skips decide, as the town rally did. In-place fighting during the wait: see the hold-ground entry above.
Consent: user (logic confirmed: planned+actual landing, NPC and scroll count as teleport, NPC-click wait removed, fight in place while waiting, first trip only; "진행").
Result: implemented. `Others/tests/test_party_rally.py` passes. Not run in game.

## 2026-10-20 — party start town rally on the leader's tile (superseded the same day)

Intent: at party start, before leaving for the hunt, the leader sends `town_rally` (`map_id`, `x`, `y` = its own tile) and stands until every roster member is within 7 tiles. Then the normal solo routine (hunt travel, NPC rally) starts. The hunt NPC rally keeps waiting for everyone, as before.
Shared: `websocket.party_orders` — `HuntRally` became `Rally` (`town_rally` and `hunt_rally` instances), new `note_positions` / `missing`; `MemberOrders.hunt` became `gather` and accepts both orders. Member reports carry `order`, so an `arrived` for one gather does not count for another. Member `_maybe_hunt_gather` walks to either point (`party_town_rally` / `party_hunt_rally` reasons). Leader report drain moved to `_drain_party_reports` (both rallies). Leader loop gate after the invite setup skips decide while waiting.
Arrival counts from a member report or from the in-game party list position (town rally only).
Affects: party leader start, party member gather. Solo, combat, HP, retreat, loot, and login are unchanged.
Side effects to watch: no timeout (user chose to wait for everyone), so a roster member who never logs in keeps the leader standing; the leader does not decide (and so does not fight) while waiting at start. An exception in the rally skips it and leaves for the hunt.
Consent: user (town rally at party start, on the leader's tile, wait for all; "이 범위로 진행").
Result: implemented. `Others/tests/test_party_rally.py` passes. Not run in game.

## 2026-10-20 — leader party invite types through the enter_chat module

Intent: the leader's Start invite (`/파티 <name>`, `파티탈퇴` to leave) typed nothing or broke Hangul through the old `InputRouter` paste path. The tested `enter_chat` DLL now types each line: Hangul as 2-beolsik jamo keys through Interception and the Korean IME, other characters as `WM_CHAR`, Enter to open and send. No clipboard, no SendInput.
Layout: native source + `bin/enter_chat.dll` in `Engine/analysis/enter_chat/`; Python output module `app._05_action.chat` (`native` binding, `handoff`, `sender.GameChat`); party lines in `app._06_party.chat_commands`; `app._06_party.setup` holds only the leave/invite flow and takes `send_line(line) -> bool`.
Shared: `mouse.release_capture` / `prepare_capture` run around each typed line, because the DLL opens its own Interception context. Only `_run_leader_party_setup` sends chat; move, combat, HP, retreat, loot, login, and member logic are unchanged.
Behaviour change: the first undelivered line (no LC window, focus, IME, elevation) is logged with the DLL status and stops the remaining invites. `send_game_chat` is removed.
Side effects to watch: the bot holds no mouse/keyboard for about 1–2 s per line at leader Start; LC is brought to the foreground and the input language is switched to Korean for the line, then restored.
Consent: user ("migrate this into this project as a new module for chatting, and use this in party logic to invite the members").
Result: implemented. `Others/tests/test_game_chat.py` and `test_party_invite_setup.py` pass, including a real-DLL dry run (`/파티 번개공격` = 8 chars, 17 keys). Not run in game yet.

## 2026-10-20 — standalone party tactics package (not wired)

Intent: add formation, movement, and focus-fire logic as independent modules under `Engine/app/_06_party/tactics/`: open-field vs narrow-dungeon classification, open-field fan slots with sight-line slot repair and pace, dungeon single-file trail with corner/lag hold for the leader, leader-jump regroup with staggered delays, focus-fire allocation with overkill prevention, and per-member volley delays. A random teleport scroll lands on a random tile, so regroup defaults to `rejoin`; repeated random teleport is opt-in for small maps.
Shared: none. Nothing imports `tactics`; follow, assist, loot, HP, retreat, login, and decide are unchanged.
Affects: nothing at runtime until wired.
Consent: user ("impl" these logics as independent modules).
Result: implemented. `Others/tests/test_party_tactics.py`, 37 tests pass. Not run in game.

## 2026-10-19 — dedicated party session log

Intent: open `Engine/logs/party-YYYYMMDD-HHMMSS.log` when party is enabled, separate from `bot-*.log`. Channels: setup (invite), session (wait/farm), member (kind changes), join (cross-map), socket (WS + local chat).
Shared: logging only. Follow, assist, HP, login, and decide paths unchanged. Member kind lines log at INFO only when kind/reason changes.
Affects: diagnosis files for party Start.
Consent: user ("go" after confirming party log system was missing).
Result: implemented. Unit tests in `Others/tests/test_party_log.py`. First live Start created no `party-*.log` because open ran before `install_profile_runtime` (party_enabled still False). Open moved to after profile apply + leader setup/socket entry.

## 2026-10-19 — party log open after profile apply

Intent: party log file was missing while Party invite still ran.
Shared: `_ensure_party_log` only. Decide/move/combat unchanged.
Affects: when `party-*.log` is created.
Consent: user (cannot see party log while doing party).
Result: implemented.

## 2026-10-19 — same-map world nav walks instead of a talking scroll

Intent: on Talking Island the character was already on map 0, and world nav still opened a talking scroll toward the pet manager. The list never opened (`opened=False`), then every tick idled on `world nav scroll land` and never walked or hunted.
Shared: `WorldNavPlanner.plan` `allow_scroll`. Cross-map scrolls, NPC teleporters, combat, and HP are unchanged.
Affects: a goal on the map the character is already on (farm routine, same-map shop). That trip walks. A goal on another map still uses the talking scroll.
Consent: user (check the log and fix; the bot is in the world and never decides).
Result: implemented. Replay of map0 (32323,32965) → (32384,33068) is one walk of 103 tiles. Not run in game.

## 2026-10-19 — revive retreat keeps the dungeon routine clock

Intent: dying and reviving was the one retreat that still started the dungeon row clock at zero on the way back. A revive retreat now freezes that clock the same way as a world-tree retreat, and the hunt-floor return resumes the saved seconds.
Shared: `hold_dungeon_routine_clock`. Arrival and floor-route release already resume a held clock, including `post_respawn`. Field rows still start a new count when a revive return arrives.
Affects: dungeon routine duration after death. Time from the revive retreat until the hunt floor is not counted.
Consent: user (keep the timer in the revive case too).
Result: implemented. Not run in game.

## 2026-10-19 — log the cell and walk line on each travel click

Intent: the player cell at a travel click was not logged, so 77 of 147 arrival pairs could not be classed as a continued client walk. Each real travel click now records the player cell, the click it replaces, the new click, the distance, both client polylines, whether the old line is a prefix, and whether the body is moving. One later line says whether the body stopped within 0.7s.
Shared: `_emit_click` and `_follow_body_click`. The click tile, the arrival rule, and avoidance are unchanged. A held hop (`mid_act`) does not add a click line.
Affects: travel log volume on dungeon patrol, floor walks, and field hops. No change to where the character walks.
Consent: user (log P, W, C, dist, both client paths, prefix, moving, and click time before changing the click timing).
Result: implemented. Not run in game.

## 2026-10-19 — dungeon routine clock pauses for a retreat

Intent: a dungeon row is one routine. Leaving it for the world tree was zeroing that clock when the hunt floor was reached again, and the time away was either discarded or still counted. The clock now freezes when a retreat starts on a dungeon row, including a revive retreat, and resumes from the saved seconds when the character is back on that hunt floor. The first arrival on a new row still starts at zero.
Shared: `hold_dungeon_routine_clock`, `release_dungeon_routine_clock`, `begin_retreat`, `_finish_dungeon_floor_route`, and world-nav arrival. `_resume_stay_clocks` does not resume a held routine clock while the bot is running. Field rows, combat, movement, HP recovery, and the farm-area stay clock are unchanged.
Affects: the routine duration of a dungeon row across mother-tree, teleport, scroll, and revive retreats. Time away from the hunt floor is not counted. A return whose reason is `post_retreat`, `post_shop`, `after_shop`, `hunt_map`, or `unstick_return` also keeps the clock when it was not held.
Consent: user (dungeon routine timer is saved and pause/resume on world-tree retreat, return, and revive).
Result: implemented. Not run in game.

## 2026-10-19 — warehouse deposit does not match the bag

Intent: an open deposit window was labeled retrieve when one displayed name differed from the bag (`펫 목걸이 [LV.5 용맹펫]` versus `펫 목걸이`), so the visit closed without storing. The open warehouse list is the deposit list. Rows absent from the keep list are stored. Adena is still skipped by name.
Shared: `writeStoreJson` mode and `execute_calibrated_sell` `read_sell_tab`. Merchant sell, the keep list, and the one-attempt warehouse stop stay as they are.
Affects: the warehouse keeper only. A list read while the retrieve tab is showing would store those rows too.
Consent: user (the open window is the deposit window; store rows that are not on the keep list; no bag comparison).
Result: implemented. The open deposit window read `open=1 mode=deposit` with 28 rows. Keep-list names stayed; the other rows, including 양초, are the deposit set. Adena was not on this list.

## 2026-10-19 — warehouse list reads the project DLL and registry

Intent: the warehouse visit loaded `Engine/analysis/NPC_conv/storewin.dll`, which looked upward for `registry\LC930_REGISTRY.txt` and never found it, so every snapshot returned `error: attach`. The visit now passes `Engine/analysis/lc930/registry/LC930_REGISTRY.txt` into `storewin_snapshot`. The window-slot offsets that file was missing are written there. `D:\dist\bin\storewin.dll` is no longer a fallback.
Shared: `storewin_reader.default_dll_path`, `default_registry_path`, and `storewin_load_reg`. Sell clicks, the keep list, and the one-attempt warehouse stop are unchanged.
Affects: the warehouse keeper list read only. Merchant sell still uses `shop_listen`.
Consent: user (yes; DLL and offsets stay in the project).
Result: implemented. With the warehouse window closed, the project DLL and project registry returned `open=0 mode=closed` and no attach error, the same result as the registry beside the build. The previous project DLL had returned `error: attach`. Restart the bot so it loads this DLL; the running process still has the old file mapped.

## 2026-10-19 — attack sight visits every cell a 1-tile fence crosses

Intent: the first attack click could land on a monster behind a one-cell fence because the sight line sampled with `round` and a diagonal step passed when only one shoulder was open. The shot now blocks when the segment touches a blocked cell, and a diagonal step needs both shoulders. A new target needs a memory nav tile. A sticky already within 2 tiles still uses the screen tile. After a dungeon fence release, that id stays out of the new-target list for 2 seconds.
Shared: `tiles_on_segment`, `line_of_sight_clear`, and `_los_step_open` in `dungeon.py`. `line_of_sight_clear` is only reached from `attack_line_clear`. Movement keeps `diagonal_open` (one open shoulder still walks). `list_attackable`, `list_attacked_me_targets`, and `nearest_attacks_me_force` drop a monster with no memory tile. `continue_or_start_combat` waits on a far sticky that has no memory tile, and `note_wall_fence_block` feeds `excluded_target_ids`.
Affects: new target choice, sticky attack continuation, and dungeon self-defense sight. Walking, loot clicks, shop, potions, retreat, and login are unchanged.
Consent: user (yes to this scope).
Result: implemented. Sight cases checked in a local script. Not run in game.

## 2026-10-19 — straight travel hops click onward while still walking

Intent: a world-nav hop stopped about half a second at every 5-tile click because the next tile was chosen only at arrival. On a straight client walk line the farther guide tile is clicked while the body is still moving, two tiles before that arrival.
Shared: `emit_travel_hop` and `_straight_extend_waypoint`. Arrival stays `_near_tile` / `travel_arrive_tiles` (1). The hop cap stays `travel_max_hop` (field 5, dungeon 3). Stuck time still resets only when the standing tile changes. An open door or the final goal stops the extension so door retarget and step completion stay as they are. Loot and search keep their own follow functions.
Affects: field world nav, farm entry, retreat, and dungeon patrol when the current guide does not turn. Corners still wait for arrival. Screen engage, loot, and mother-tree heals still interrupt the walk.
Consent: user (straight-line extend only, keep every existing workflow).
Result: implemented. Not run in game.

## 2026-10-19 — warehouse keeper finishes after one attempt

Intent: after the warehouse keeper ran once, a failed storewin read (retrieve, closed, or no snapshot) closed the window and clicked the same NPC again. One `give_goods` attempt now ends that step whether the list read succeeded or not. Merchant sell still retries only on success.
Shared: `ActionController._shop_run`. `execute_calibrated_sell` and storewin are unchanged. A store behavior id (`give_goods` / `store_*`) sets `shop_ok` after the attempt returns, so `advance_sell_trip` runs the same path as a successful deposit. Sell, buy, and teleporter still require `ok`.
Affects: the warehouse stop after an overweight or pre-retreat sell. The following step is unchanged: retreat when this trip was sell-then-retreat, otherwise the post-shop return. A failed open still leaves the keeper.
Consent: user (finish the warehouse once the attempt is done, not according to the result).
Result: implemented. Not run in game.

## 2026-10-19 — give-up list lasts 4 seconds

Intent: a given-up monster stayed off the target list for 160 decision ticks, which is not a fixed time. The skip is now 4 seconds of wall clock.
Shared: `give_up_target` stores `time.time()`. `active_give_up_ids` drops rows older than `GIVE_UP_COOLDOWN_SECONDS` (4). `excluded_target_ids` and sticky rebind (`_living_same_species`) both use that set. Cursor-reject 4 seconds, the session blacklist, and loot abandon stay separate. The old `give_up_cooldown_ticks` setting is ignored.
Affects: farming, travel combat, dungeon patrol, and retreat's "enemy nearby, do not loot" check, whenever a target is given up (combat blocked, max engage, scarecrow level). After 4 seconds that id can be chosen again. A monster that is still inside the 4 seconds is still skipped, including one that is attacking.
Consent: user (the give-up cooldown must be 4 seconds, not 160 ticks).
Result: implemented. Not run in game.

## 2026-10-19 — an open door is crossed by the next path tile

Intent: a normal cursor on a tile beside an open door left the character on the near side of the fence. When this hop's guide passes through an open door, the click is the next guide tile after that door, one step past the usual hop cap when that step is what clears the doorway. If that tile is outside the click region or the line is closed, the hop does not substitute a side tile. A door cursor on the far tile tries the following guide tile. A closed door is still clicked once. A not-permitted door stays a wall.
Shared: `select_click_waypoint`, `plan_body_click`, and the travel click probe in `_search`. Combat, loot, HP, and login clicks stay as they are.
Affects: patrol, dungeon floor hops, and other ground hops whose guide crosses an open door.
Consent: user (yes; click the tile beyond the open door).
Result: implemented. Retarget check passed. Not run in game.

## 2026-10-19 — door cursor opens only a closed door

Intent: a door cursor on an open door was still clicked, which shut the door, while the nav map kept treating the tile as open. A door cursor now clicks only when the live door state is `close`, and that click is once so the repeat does not shut it again. `open` and `unknown` skip that point and try another tile in the hop ring. `not_permitted` is a wall for pathfinding even when the map tile is white.
Shared: `travel_click` ground hops (`_search`), the first `cursor_ok` check in `_click_until_walk`, and `TerrainMap.is_walkable` via the live door-wall set. Combat, loot, HP, and login clicks are unchanged.
Affects: travel, patrol, and loot-approach hops in dungeons and on the field. `print_state` must be rebuilt so entity rows carry `door`; until that DLL is loaded, a door cursor has no `close` state and is not clicked.
Consent: user (click the door only when it is close; pass through when open; treat not_permitted as a wall).
Result: implemented. Policy and wall-tile check passed. `Engine/analysis/entities/print_state.dll` rebuilt (newer than `print_state.new.dll`, so the loader uses it). Not run in game. Restart the bot so the new DLL loads.

## 2026-10-19 — a floor-route exit keeps the outside door

Intent: leaving during a dungeon floor walk flipped mapId while xy was still the inside cell. The next `hunt_map` plan measured that cell against the outside door and took a talking scroll plus a paid teleporter. The world-nav walk correction did not run, because this walk is the floor route.
Shared: `_drive_dungeon_floor_walk` calls the existing `_remember_stale_exit_landing` when the live map is no longer the walk step's map. The next world-nav arm still uses that outside landing once. The 50-tile door check is unchanged.
Affects: a floor-route walk that steps through a known exit, then `hunt_map` replans. Same-map floor walks, shop scrolls, HP retreat scrolls, and combat stay as they are.
Consent: user (yes; portable rebuild later).
Result: implemented. Check passed for map 1 `(32669,32802)` onto map 0: landing `(32478,32851)`, scroll off. A start at the goods shop `(32642,32949)` still scrolls. Not run in game. Portable not rebuilt.

## 2026-10-19 — Holy Weapon presses its hotbar key twice

Intent: one press of Holy Weapon only raised the round skill cursor, so the buff never landed and the character could not attack. Weapon buffs already use a second key tap (`power_up` / `CAST_DOUBLE`). Checked buffs with that role now take the same second tap. Shield and other single-press buffs stay one tap. Heal and teleport are unchanged.
Shared: `_press_catalog_buff` only. `_press_assigned_skill` is not used for this path.
Affects: checked Holy Weapon, Enchant Weapon, and the other weapon-buff names on that role, during hunt, travel, and dungeon buff ticks.
Consent: user (one press leaves the skill cursor; it needs the second press).
Result: implemented. Not run in game.

## 2026-10-19 — warehouse visit follows the store-after-sell box

Intent: the warehouse keeper ran whenever leftovers remained outside the keep list. Visit `give_goods` only when equipment `store_after_sell` is checked. The box defaults to checked. Unchecked ends the sell trip after the four merchants.
Shared: `advance_sell_trip`, `STORE_AFTER_SELL` via schedule → profile → `configure_decision`. Sell clicks, buy, HP, login, and combat stay as they are.
Affects: the warehouse stop after an overweight or pre-retreat sell.
Consent: user (visit only if the box is checked; checked by default).
Result: implemented. Not run in game.

## 2026-10-19 — checked buffs recast from the magic table

Intent: auto-use on the individual magic table chooses which lasting buffs are kept up. When the live buff is missing or has 10 seconds or less left, the matching hotbar key is pressed, one skill at a time, in priority order. MP still has to clear the reserve. Heal, teleport, attack magic, and the haste potion stay on their existing paths.
Shared: `due_buff`, `maybe_cast_buff`, `_maybe_support_spells` (call site unchanged). `apply_hp_actions`, `maybe_heal_after_teleport`, and `try_unstick_teleport` are unchanged. Armor and weapon buffs no longer fire from the old role order unless that skill is checked.
Affects: hunt, travel, and dungeon ticks that allow buffs. A checked skill that is not on the hotbar is skipped. Potions, login, and selling stay as they are.
Consent: user (yes).
Result: implemented. Resolver and due-buff check passed. Not run in game.

## 2026-10-19 — warehouse deposit reads storewin

Intent: `give_goods` was clicking with the merchant sell list. The warehouse window list comes from storewin. Only the deposit tab is used. Rows outside the keep list are stored with the same scroll flicks, cursor hold, and 0.2–0.5s click gap as the four merchants. Adena is skipped by name. A retrieve list is not clicked. The four merchants still use shop_listen, and the warehouse stay last.
Shared: `storewin_snapshot`, `storewin_reader`, `execute_calibrated_sell` when `action` is store. Buy, HP, login, and combat stay as they are.
Affects: the warehouse stop at the end of an overweight or pre-retreat sell. A scroll that rewrites the window vector was not checked in game; the reader walks the full slot vector (the sample was 29 rows).
Consent: user (yes).
Result: implemented. `storewin.dll` built and loaded; with the game closed the snapshot returns `mode=closed`. Not run in game.

## 2026-10-19 — sell item clicks wait 0.2–0.5s; scroll leaves the cursor

Intent: item-row clicks used a fixed 0.5s before and after the quantity. Each sell-row click now waits a random 0.2–0.5s, then the quantity is typed with no second wait. The sell-list wheel no longer moves the cursor to the scroll point; it stays on the last item clicked. Buy still moves to its scroll point.
Shared: `execute_calibrated_sell`, `_scroll_list(move=False)` on the sell path only. Confirm, buy, keep list, and the 5/6/7 flick size stay as they are.
Affects: overweight sell, pre-retreat sell, and warehouse deposit (same sell function).
Consent: user (0.2–0.5s between item clicks; cursor stays on the last item while scrolling).
Result: implemented. Not run in game.

## 2026-10-19 — sell list flicks 5, 6, or 7 rows

Intent: after the first screen, the sell dialog advanced one row at a time and clicked one item. Each later flick now rolls 5, 6, or 7 rows, then clicks the rows that came into view. A row already clicked is left alone when it is still on screen. The flick shortens at the bottom of the list so the click stays on the right row.
Shared: `sell_scroll_clicks`, `execute_calibrated_sell`. Warehouse deposit uses that function, so it flicks the same way. Keep list, Adena skip, the four-NPC shuffle, buy, HP, login, and combat stay as they are.
Affects: overweight sell and the pre-retreat sell, and warehouse deposit.
Consent: user (scroll 5, 6, or 7 rows, chosen at random).
Result: implemented. Plan check passed for chunks 5, 6, and 7, including a short list and keep-list gaps. Not run in game.

## 2026-10-19 — shuffle the four sell NPCs; one sell dialog selects every row

Intent: the four merchants were always visited in a fixed order, and each sell confirm closed the window after one scroll page. Visit those four in a random order. In one open Sell tab, scroll through every row outside the keep list, then confirm once. The warehouse keeper stays after the four, and only when the bag still holds something outside the keep list.
Shared: `shop_trip._shuffled_sell_ids` (used by `_begin_sell_queue` and `arm_sell_before_hp_retreat`). `execute_calibrated_sell` and `sell_scroll_clicks`. `give_goods` is still appended in `advance_sell_trip`. The keep-list filter, Adena skip, buy path, HP, login, and combat stay as they are. Warehouse deposit uses the same sell function, so it also selects every row before one confirm.
Affects: overweight sell trips and the pre-retreat sell. A scroll that clears already selected rows would drop those rows; this path does not reopen the shop to finish them. Rows past 80 are left for the next merchant or the warehouse.
Consent: user (yes).
Result: implemented. Scroll-click plan checked (first seven rows need no wheel; later rows scroll only the extra notches). Not run in game.

## 2026-10-19 — low HP heals in place, teleports once while hit

Intent: at the retreat HP, a character who was not being attacked still left for the world tree, and a character who was being attacked did not teleport before that. Heal and teleport could also be pressed below 20 MP on the unstick path and at the key itself.
Shared: `apply_hp_actions`. At or under the retreat row, a monster or summon whose attack targets the character teleports once when that skill can spend mana. The same drop does not teleport again until HP rises above the retreat row; the world tree, talking scroll, then teleport ladder runs instead. With nobody attacking, and heal able to spend mana, the combat lock is released and heal stays in place, including while the heal key is cooling. Dungeon and field hunting share this. Heal and every teleport refuse known MP below 20 at the decision and at the key press. Unstick keeps its percent reserve on top of that floor. The mother-tree mana floor stays. Potions, the 95% safe-zone fill, world-tree 40/80 recharge, and the fallback ladder stay as they are.
Affects: field and dungeon HP recovery at the retreat percent. Stuck escape will not teleport below 20 MP.
Consent: user (yes, keep every other behavior).
Result: implemented. Not run in game.

## 2026-10-19 — a stuck gate click steps aside once

Intent: a dungeon door click that did not move the character still waited 5 seconds twice on the same tile. Bodies on the entrance were never sidestepped during that wait.
Shared: `run_gate_click` returns `gate stuck pose unchanged` when mapId and the tile are both unchanged for the full 5 second land wait, and does not take the second ring from that tile. A moved tile or a flipped mapId still finishes that wait and may take the second ring. World nav and the dungeon floor route then emit one existing body-avoid hop (`emit_gate_sidestep` / `plan_body_click`, one tile) and the same gate click once more. A second stuck click fails the transition as before. The first cut was 1 second; the user set it to 5 seconds before any game run.
Affects: world-nav map transitions and dungeon floor gate clicks. Shop, HP retreat, talking scroll, NPC teleporter, and combat engage stay as they are.
Consent: user (yes).
Result: implemented at 5 seconds. Gate-watch check passed (unchanged tile is stuck at 5s; at 1s it still waits; a moved tile and a flipped mapId keep waiting). Not run in game.

## 2026-10-19 — near a dungeon door, world nav walks and clicks

Intent: a hunt that slipped out next to the dungeon door still took a talking scroll to a town hub when the click point was more than 10 tiles away. The 50-tile door check already dropped the NPC teleporter.
Shared: `WorldNavPlanner.plan`. When `near_goal_ground_enter` is true (50 tiles, the same check that drops the NPC teleporter), talking-scroll edges are omitted for that plan. The walk to the `ground_enter` and the click stay. A separate 10-tile or 15-tile scroll radius was tried and removed; the user kept 50. Farther starts, same-map plans, shop scrolls, HP retreat scrolls, and the in-dungeon floor route are unchanged.
Affects: world-nav returns that begin within 50 tiles of the goal map's ground door. A blocked walk still fails that plan instead of scrolling.
Consent: user (yes; 50 tiles, no separate 10 or 15).
Result: 50-tile check restored. Planner check passed (30 tiles: walk+click, scroll and NPC teleporter off; 80 tiles: both on). Not run in game.

## 2026-10-19 — exit replan starts at the outside door

Intent: leaving a dungeon flipped mapId while xy was still the inside cell, so the 50-tile door check measured about 200 tiles and took a talking scroll plus a paid teleporter.
Shared: a world-nav walk that leaves its map (`left map during walk` / `walk on wrong map`). When the live xy is within 5 tiles of that exit's inside cell, the next plan starts at the exit's outside landing, once. The existing 50-tile check then drops the talking scroll and the NPC teleporter. A start that is not on that inside cell is unchanged.
Affects: the replan after a world-nav walk steps through a known exit. Same-map walks, shop scrolls, HP retreat scrolls, and in-dungeon floor clicks stay as they are.
Consent: user (yes).
Result: implemented. Check passed for the 12:08 pose `(32811,32723)` leaving map 7: landing `(32728,32928)`, scroll off. `(33055,32342)` keeps the scroll. Not run in game.

## 2026-10-19 — safe-zone retreat heals and drinks until hunt resume

Intent: with the world tree unavailable, heal and potions stopped at the Recovery-tab percents while the character still waited until 95% HP to leave the safe zone.
Shared: `apply_inplace_hp_support` and the HP-potion side intent. On an HP retreat that is not a mother-tree trip, both continue until `HP_ALMOST_FULL_RATIO` (95%). Heal still requires enough MP to cast. A heal cast on that tick skips the potion. Hunting keeps the tab percents. Mother-tree recharge keeps its 40% / 80% band.
Affects: the wait after an HP retreat to a safe zone or teleport landing. MP retreats and return-to-town retreats are unchanged.
Consent: user (yes).
Result: implemented. Not run in game.

## 2026-10-19 — cursor reject skips that monster for 4 seconds

Intent: a clipped monster failed the attack cursor, the sticky lock kept aiming at it, then the id sat on the 160-tick give-up list. After the body walked fully on screen the character still ignored it.
Shared: `note_cursor_verify_fail` for monsters. Five rejected attack cursors in a row on the same id clear the sticky lock and record that id in `cursor_reject_until` for 4 seconds. An accepted cursor clears that streak. `excluded_target_ids` hides the id from the next attack choice, including a monster that has attacked me. Item cursor misses, dungeon wall release, and the 160-tick give-up for abandon / max engage / combat blocked stay as they are.
Affects: farming, travel combat, and dungeon patrol whenever an attack click is rejected. A monster released this way can be chosen again after 4 seconds. Other monsters can be chosen during those 4 seconds.
Consent: user (yes; 4 seconds instead of 160 ticks; exclude only after 5 cursor rejects in a row).
Result: implemented. Not run in game.

## 2026-10-19 — pause freezes the routine and hunt-area clocks

Intent: both stay clocks were wall time, so a pause still burned the row and the hunt area. The countdown kept falling, and a long pause advanced the row on resume.
Shared: `RoutineCursor` elapsed time and `farm_time` sampling. Pause, auto-pause, a minimized window, a missing game window, and a paralyzed cursor commit the open segment and hold it. Resume continues from those seconds. The short wait for a live position at start still counts. Stop still drops both clocks, and the next start is the first row at zero. Arrival reset, return trips that keep the row clock, the Moving label, login, combat, and HP stay as they are.
Affects: the routine-row countdown and the hunt-area stay, on screen and in the expiry check.
Consent: user (yes, freeze both clocks on pause and continue on resume).
Result: implemented. Not run in game.

## 2026-10-19 — off a dungeon floor, world nav starts again

Intent: a dungeon hunt resumed on the mainland (world tree) kept the old floor patrol and fought there. The hunt-map check treated every mainland tile as the dungeon return town, because that town is the Giran teleporter row and its geography is the whole mainland pack.
Shared: `_maybe_scroll_to_hunt_map` no longer returns early for that town. Off the scheduled floor, and not on another floor of the same complex, it still calls `begin_world_nav` with reason `hunt_map`. `on_dungeon_return_town` is removed. `finish_retreat` and `begin_world_nav` stay as they are.
Affects: travel and farming while a dungeon row is active and the live pack is not that dungeon. A pause/resume at the world tree, and any other mainland tile, arms world nav back to the dungeon. Another floor of the same complex still uses the floor route. Shop trips, scroll-arrival waits, and an already armed world nav stay blocked. Field hunts are unchanged.
Consent: user (ok, remove the return-town skip; do not add a separate resume path).
Result: implemented. Not run in game.

## 2026-10-18 — one stair goal per floor, and start inside the dungeon

Intent: dungeon floor walks were a new travel every 3 tiles, so the character stopped at each one. A start already on the scheduled floor (or another floor of that same complex) still planned world nav back to the entrance and scrolled to town.
Shared: `steps_from_segments` now emits one WALK, the stair cell, then the existing gate step. `emit_travel_hop` still cuts that walk into 3-tile clicks and sends the next click when a hop arrives. `arm_world_nav` reads the live MapSubsystem map before planning. The scheduled floor marks arrival and loads that floor's patrol. Another listed floor of the same complex sets the hunt id and returns to farming so the floor route starts there. A field, another dungeon, or an entrance-floor row still plans world nav. `begin_travel`, the gate executor, avoidance, and `DUNGEON_MAX_HOP_TILES` stay as they are.
Affects: every deeper-floor dungeon row at Start and while climbing. Entrance-floor rows and field hunts keep the previous arm. Patrol click length is unchanged.
Consent: user (ok, after the log analysis of the 3-tile stops and the Gludio F3 restart).
Result: implemented. Floor calculator checks passed (one walk per floor, F1 goal unchanged). Not run in game.

## 2026-10-18 — dungeon floors above the entrance use a calculated route

Intent: a hunt scheduled on a deeper dungeon floor still enters through the existing world-nav gate, then walks logical cells to that floor. The cells come from the shared floor calculator. Travel, avoidance, combat, and the gate click stay on the current executors.
Shared: `goal_for_entry` stops world nav on the complex entrance when the row is a deeper floor. `_on_world_nav_arrived` and the already-there arm do not load that floor's terrain or start its clock until the live map is the scheduled floor. `_maybe_scroll_to_hunt_map` does not re-arm world nav while the live pack is a listed floor of that same complex. `finish_retreat` resumes the floor route in that case and still world-navs from anywhere else. `_step_dungeon_off_floor` idles only for an entrance-floor hunt; a deeper floor calls `begin_travel` for each logical cell and `ActionType.GATE` for a `floor` link. `apply_gate_result` records that gate outcome with the existing land check. Travel engage during the walk is the same `farm_loot_or_combat` patrol travel already uses.
Affects: dungeon rows whose floor is deeper than the ground entrance (Gludio F2 and below). An entrance-floor row (Gludio F1) keeps the previous world-nav goal, gate, terrain load, and patrol. Field hunts, login, HP, and unstick are unchanged. `patrol.yaml` is not written.
Consent: user (add in-dungeon floor travel; use only the route coordinates; keep existing movement, avoidance, and attack).
Result: implemented. Checked with the floor calculator (F1 goal unchanged, F2/F3 step order, family mismatch, failed gate does not advance). Not run in game.

## 2026-10-18 — finished world nav does not keep the first hunt area

Intent: after a talking-scroll walk into the second hunt area, the session ended but `travel_purpose` stayed `world_nav`. The stay clock then watched the first checked area, so the second area's minute froze and the character never left for the third.
Shared: `_on_world_nav_arrived`, `_drop_world_nav_session`, and `clear_world_nav_run` clear that purpose. `trip_destination_farm` follows a world-nav trip only while the session exists; afterward the clock uses `farm_area_index`. The area-list "Moving" flag does the same. Walk target, combat, and HP stay as they are.
Affects: the hunt-area countdown after a world-nav arrival on Talking Island and the mainland, and the move to the next checked area when that minute ends.
Consent: user (yes, clear the purpose so the timer keeps the current area).
Result: implemented. Not run in game. A `nav` line `world nav purpose cleared` is written when the leftover purpose is dropped.

## 2026-10-18 — checked user areas stay on the hunt list

Intent: a map reload was replacing the checked hunt areas with the shipped pack `farms.yaml`. Areas drawn only in the user file (mainland 구역 7, 구역 8) stayed checked in the dialog but were missing from the running hunt list and its timer.
Shared: `ensure_navigation_for_pack_id`, after `configure_navigation_for_map`. When the live pack is the active battle row, the checked overlay rects are loaded again. A break row, a dungeon, or a different map does not get those rects. The tour is cleared only when that name list changes. Stay clock, walk target, combat, and HP stay as they are.
Affects: the hunt list and area timer on Talking Island and the mainland after Start and after a map sync. Unchecked shipped areas are not put back on the list.
Consent: user (yes, keep the checked user areas when the map reloads).
Result: implemented. Not run in game. A `nav` line `checked farms remounted` lists the names.

## 2026-10-18 — hunt-area stay no longer waits for the center

Intent: after the edge-start change, the countdown still began when the walk reached the area center. World-nav arrival loads the hunt row and was still calling `reset_farm_timer` for reasons such as `start` and `same_map_routine`. Until that arrival the clock also followed the loaded farm slot, not the rectangle the walk is entering.
Shared: `sample_farm_presence` times the trip's destination rectangle once the live map matches that pack. `apply_routine_entry_runtime` resets the stay on a new row, and on arrival only when that farm has not already started. The area-list clock highlights that destination while the trip is outside (`Moving`) and counts down after the tile is inside the rect. The walk target stays the center. `is_inside_active_farm` is unchanged for empty-area and yield checks.
Affects: the hunt-area countdown on the way into a Talking Island or mainland area, including the first walk after Start and a same-map routine change. Login, combat, and HP stay as they are.
Consent: user (timer should start as soon as the character enters the hunting area; reported that it still waited for the center).
Result: implemented. Not run in game. `farm stay start` logs the farm name and the nav tile of the first inside sample.

## 2026-10-18 — hunt-area stay starts at the rectangle edge

Intent: the stay clock was zeroed when world nav or the next-farm walk arrived at the area center, so the countdown began only after that point.
Shared: `reset_farm_timer` no longer runs on next-farm arrival or on `farm_area` world-nav arrival. It runs when the tour advances and when a new routine row loads its farms. `sample_farm_presence` still adds time only inside the active rectangle. The area timer shows the countdown once the character is inside, and `Moving` only while the trip is still outside that rectangle.
Affects: the hunt-area stay on Talking Island and the mainland, including the walk from the edge to the center. Login, combat, and HP stay as they are. The walk target is still the center.
Consent: user (timer should start as soon as the character enters the hunting area).
Result: implemented. Not run in game. A `nav` line `farm stay start` is written on the first inside sample of a fresh stay.

## 2026-10-18 — field same-map moves use world nav

Intent: a routine-row change or a hunt-area change on Talking Island or the mainland should use the same world-nav plan as a map change, including a talking scroll when that costs less. A failure of that trip must not skip the routine row.
Shared: `take_next_routine_if_due` for packs `talking_island` and `mainland` arms reason `same_map_routine`. `_try_farm_upkeep` on those packs arms reason `farm_area` toward `farm_area_index`. `goal_for_entry` reads that index for `farm_area`. Arrival keeps the index and starts the farm stay clock; the row clock is not reset. Other maps keep the old same-map rule. Cross-map failure still calls `_fail_skip`.
Affects: travel between hunt areas and between routine rows on Talking Island and the mainland. Dungeon floors, login, combat, and HP stay as they are.
Consent: user (yes; log those trips; only the two field maps).
Result: implemented. Not run in game. On failure the `nav` log and `[world_nav] STATE=FIELD_NAV_FALLBACK` record reason, error, and `via=walk` or `via=retry`. The row stays. Arm and arrival log `field world nav ...`.

## 2026-10-18 — return to the farm area that was left

Intent: after retreat or a shop trip, the walk back used the first checked farm. The character should return to the area index they left, including a Mother Tree or shop landing.
Shared: `goal_for_entry` and `apply_routine_entry_runtime` for reasons `post_retreat`, `post_shop`, `after_shop`, `hunt_map`, and `unstick_return`. The index is saved once in `begin_retreat`, `begin_shopping`, `tick_shop_trip`, and before a scroll/Mother Tree map reload. A new routine row still starts at the first checked area. Break rows still walk to the first checked rest area. Login, combat, and HP stay as they are.
Affects: the walk home from town, the world tree, and a shop, and the farm index after that arrival. A changed schedule row does not reuse the old index.
Consent: user (yes, that return scope).
Result: implemented. Not run in game.

## 2026-10-18 — confined episode log

Intent: a 13 s stay inside Chebyshev radius 3 does not say whether the character was against a wall or weaving. The next log needs the path from that window.
Shared: `note_confined_progress` still fires at 13 s / radius 3. It now keeps one episode and writes a `nav` line when the 13 s elapse (`kind=fire`) and when the character leaves the bubble (`kind=leave`). Combat and shopping still clear the clock without a line. Teleport, the talking scroll, and the radius stay as they are.
Affects: island and travel confined logging only. The line carries anchor, cell, elapsed, stepped distance, distinct cells, waypoint start/now/changes, verified click tile and its changes, moving 1/0/unread ticks, closed click lines, and body-avoidance hops.
Consent: user (add the episode summary, leave the gate).
Result: implemented. Not run in game.

## 2026-10-18 — travel hop does not arrive across a fence

Intent: a hop waypoint one tile away counted as arrived by Chebyshev distance alone. Standing on the near side of a fence completed the hop without crossing.
Shared: `_near_tile` in `travel.py`. Same tile is still arrived. Chebyshev 1 is arrived only when `can_step` opens that edge. No terrain map keeps the distance check. `travel_arrived`, farm arrive radius, patrol, loot, login, combat, and HP stay as they are.
Affects: every travel hop (world nav, shop, retreat). A character against a fence keeps that hop and clicks it again.
Consent: user (yes, this hop-complete check).
Result: implemented. Not run in game.

## 2026-10-18 — drop the 3-standstills-in-20s escape

Intent: three separate 5-second stops inside 20 seconds no longer skip the nearby clicks. A pocket is already the 7×7 / 13 s clock. One stop is already the nearby-click sweep.
Shared: `try_movement_unstick`. Low HP still skips the sweep and teleports or uses the talking scroll. The 13 s bubble, the radius-3 clicks, and the radius-2 escalate ring stay. Login, combat, and the HP gate stay as they are.
Affects: travel, search, and loot walks inside a farm. A third stop more than 3 tiles from the last one now clicks nearby tiles instead of leaving immediately.
Consent: user (remove the 20-second, 3-stop rule).
Result: implemented. Not run in game.

## 2026-10-18 — confined bubble radius 5 → 3

Intent: a 20×18 world window makes Chebyshev radius 5 an 11×11, more than half the view. Radius 3 is a 7×7. One field hop of 5 tiles leaves it, so local search no longer counts as confined. 13 seconds stays.
Shared: `note_confined_progress` / `try_confined_escape`. Nearby-click radius 3, the radius-2 escalate ring, the enter-farm radius-5 ring, hop cap 5, and the 13 s clock stay. Dungeon still disables this escape. Login, combat, and HP stay as they are.
Affects: island and travel confined escape. A character who moves 4 or more tiles from the anchor restarts the 13 s clock. Weaving inside the 7×7 for 13 s still teleports or uses the talking scroll.
Consent: user (keep 13 seconds, change 5 to 3).
Result: implemented. Not run in game.

## 2026-10-19 — party wait logs until farm start

Intent: keep the party websocket monitor log (do not clear it on connect). Until follow/farm actually starts, write a wait line every 2.5s: in_party, party-memory leader, xy, map, seen name, dist, kind, reason, socket state. Leader Start also logs the roster and that `/초대` is in-game chat after the world is ready, not the WS local test. Member Start says follow uses party_listen, not the socket.
Shared: none. Follow, invite commands, and combat are unchanged.
Affects: party leader and member session logs until the first farm/follow action.
Consent: user (member never found the leader; invites not seen; leave the log until farm start).
Result: implemented. Not run in game.

## 2026-10-19 — leader roster invite at bot start

Intent: when the leader bot starts, open the party socket first, then type the in-game party commands for the roster table. Leave with `파티탈퇴` if this character is already in a party and is not the in-game leader. Invite each table name with `/초대 <name>` + Enter. Names already in the party, and this character, are skipped. Empty table does nothing.
Shared: none. Solo farm, member follow, `begin_retreat`, and HP lines are unchanged. Chat uses the existing Interception paste path (`InputRouter`).
Affects: party leader only, once per Start, after live origin/mapId and before the first farm decide.
Consent: user (socket first, then invites from the party table).
Result: implemented. Not run in game.

## 2026-10-19 — party loot priority (loot first / follow first)

Intent: a party-farm member can choose loot first or follow first on the party tab. Loot first: when assist, close-in, defend, join-map, wait, and stop are not needed (policy is HOLD or FOLLOW), the member walks to party drops and picks them up within the follow distance, then follows. Party adena and items are treated as its own (no ownership gate), but only the closest eligible member takes each pile. Eligible = party list members except the leader and the wizard; the local wizard never takes them. Ties go to the lower name so every client picks the same looter. Follow first keeps the earlier loot timing and the Random / Role rules.
Shared: `try_party_hold_loot`, `find_party_pickup_range_loot`, `arm_party_loot_side` gained an optional item filter (default unchanged). Side F4 on loot first still only while the leader is not fighting. Solo farm, `begin_retreat`, and the retreat HP line are unchanged.
Affects: party-farm member loot vs follow order when `party.loot_priority` = `loot`. Default `follow` = unchanged behavior.
Caveat: the wizard class id from the party list is assumed to be 3 (Lineage order). Not confirmed against live memory.
Consent: user (closest member except leader and mage loots; UI loot/follow priority; implement).
Result: implemented. Not run in game.

## 2026-10-19 — party member uses the solo retreat line at the HP gate

Intent: when a party member's HP is at or under the solo retreat threshold, call that same survival line so an elf goes to the mother tree and any other class takes the talking-scroll landing (teleport only if the scroll cannot). Follow, hunt-NPC walk, and buffs wait until that trip ends. After HP recovers, the solo hunt-map world nav is not run; the member follows the leader again.
Shared: called, not edited — `apply_hp_actions`, `tick_retreating`, `tick_shopping`, `begin_retreat`.
Affects: party member only, and only at the retreat HP gate or while that retreat or its pre-retreat sell is in progress.
Consent: user (in that situation, call that line and escape).
Result: implemented. Not run in game.

## 2026-10-19 — party hunt NPC and mother-tree orders

Intent: the moment the leader's route picks an NPC teleporter, tell members (`type` `hunt_move`, `from` `leader`, the NPC map and xy). The leader stands on that NPC until those members report they are there, then the existing teleporter click runs. A mother-tree recovery decision sends `type` `recovery` immediately. Members do not act on `recovery`. Members who receive `hunt_move` walk to that NPC, then send buffs and the item list (`type` `report`).
Shared: `WorldNavSession.begin` calls an optional plan hook; `_start_npc_teleporter` waits only when that hook is installed (leader process). Solo leaves the hooks empty, so the click is unchanged. `begin_retreat` is not edited.
Affects: party leader world-nav NPC click, party member follow while a hunt order is active, party socket payloads.
Consent: user (send the NPC and mother-tree decision at once; members gather, report, then the group goes on; leave mother-tree behavior for later).
Result: implemented. Not run in game.

## 2026-10-19 — party brain seats only (no live decide change)

Intent: add four decision-adoption seats under `_06_party/brains` — leader, member (single party bot foundation), mage, shopkeeper.
Shared: none. `PartyMemberManager.decide`, follow, assist, HP, and login stay on the current path. MemberBrain can wrap the existing manager when constructed; session does not call it yet. Leader, mage, and shopkeeper return `ready=False` and no intent.
Affects: new package only.
Consent: user (compose these modules first).
Result: implemented. Not wired into the session.

## 2026-10-17 — settle/loot when leader stops; clearer party WS probe

Intent: with the leader idle, the member kept follow distance and skipped loot because settle required an exact cardinal tile. Hold as soon as distance ≤ stop; settle uses Arrive tolerance; clear a far travel sticky goal on stop; party-farm loot only while `leader_stopped` and near stop. Member WS test TCP-probes first and tells the user to Start the leader bot.
Shared: `follow_kind` (stopped), manager settle/loot, `_start_party_client`, party tab WS test.
Affects: party-member idle settle + loot; WS diagnose UX.
Consent: user ("leader stopped then loot… keeping distance… connection is failing").
Result: implemented.

## 2026-10-18 — shortest walk after a talking-scroll landing

Intent: after the scroll lands on the nearest hub, the walk to the hunt area was following the 32-tile cluster corridor. From the Silver Knight inn that corridor leaves by the south door, while the tile path through the north door is shorter.
Shared: the world-nav walk whose previous step is a talking scroll. That walk's hops use the tile path. Other walks keep the cluster corridor. The inn south wall seal stays. Login, combat, and HP stay as they are.
Affects: the walk from a talking-scroll landing to the hunt area. At the inn the route leaves through (666, 1248).
Consent: user (after landing on the nearest hub, take the shortest way to the hunting area).
Result: implemented. Not run in game.

## 2026-10-18 — reopen the Silver Knight inn north exit

Intent: the north opening (666, 1248) is white on nav.png. The load path was marking it unstandable, so a walk out of the inn could use only the south gap.
Shared: mainland terrain load only. (666, 1248) stays walkable. The south wall y=1256, x=656–669 except (660, 1256), stays unstandable. Login, combat, and HP stay as they are.
Affects: the walk out of the Silver Knight inn. The shorter route to the hunt area leaves through (666, 1248).
Consent: user (reopen that north tile, keep the south wall seal).
Result: implemented. Not run in game.

## 2026-10-18 — seal the Silver Knight inn wall

Intent: after a talking scroll into the inn, the first hop clicked the south wall. Those cells are white tiles with a north fence, and the load path was clearing that fence, so both the white-tile path and the click check treated the wall as an open door.
Shared: mainland terrain load only. The south edge y=1256, x=656–669 except (660, 1256), and the north hole (666, 1248), become unstandable. The earlier fence clear on (668, 1256) and (669, 1256) is removed. Scroll to the inn, login, combat, and HP stay as they are.
Affects: the walk out of the Silver Knight inn. The exit that remains is (660, 1256).
Consent: user (seal that wall, keep the south gap, close the north hole).
Result: implemented. Not run in game.

## 2026-10-18 — inn door, nearest unstick hub, world-nav return

Intent: the Silver Knight inn door is open in game and fenced on the walk map, so a walk from the inn hub never crosses it. A confined escape on the mainland always scrolls to the Giran teleporter. After that landing, the same map is treated as already on the hunt map, so the return walks with enter-farm and does not arm world nav.
Shared: mainland fence tiles (668, 1256) and (669, 1256) opened when the pack loads. `farm_return_scroll_spot` for mainland now picks the talking-scroll hub nearest the active farm; Talking Island stays on 마법서 상인, and a dungeon floor still uses the fixed mainland row. After that mainland escape scroll lands outside the farm, `begin_world_nav` reason `unstick_return` runs instead of enter-farm. That arrival does not reset the routine stay clock.
Affects: walks out of the Silver Knight inn, confined-escape scroll target on the mainland, and the return after that scroll. Login, combat, and HP selection stay as they are.
Consent: user (open the inn door on the walk map; mainland confined scroll to the hub nearest the current hunt area; after that scroll lands outside the farm, re-arm world nav even on the same map so the return can use a talking scroll).
Result: implemented. Not run in game.

## 2026-10-17 — talking-scroll row returns to the hunt button

Intent: the missed row click on the customer PC was a second mouse, ChangZhi Virtual Mouse. Disabling that device made the hunt button work. The row click goes back to `move_and_click`, the same packet as ground and attack clicks. The autologin `click` path used only for that row is removed.
Shared: `_use_talking_scroll` only. `MouseController.click`, hover, the wheel, and the login flow stay as they are.
Affects: the talking-scroll list row. Other clicks stay as they are.
Consent: user (revert the scroll row to the hunt button packet; the extra mouse device was the cause).
Result: implemented. Portable `mouse` and `controller` modules rebuilt.

## 2026-10-17 — talking-scroll row closes the login driver after the click

Intent: the scroll row uses autologin's click. After a real login, that context is destroyed and `restore_desktop_input` drops the topmost flag and lifts stuck keys so the mouse works outside the game. The row click was reopening the hunt devices without that restore, and the desktop mouse was lost again.
Shared: `click_scroll_row` only. Before `shutdown` the login filter is set to none. Then `restore_desktop_input`, then `prepare_capture`, then the hunt filter is set to none. `MouseController.click` and the login flow stay as they are.
Affects: the moment after a talking-scroll row click. Other clicks stay as they are.
Consent: user (the post-login driver close was missing after the scroll row, and the outside-window mouse loss came back).
Result: implemented. Portable `mouse` module rebuilt.

## 2026-10-17 — talking-scroll row calls the autologin click

Intent: a hand click and autologin both select the talking-scroll row on the customer PC. The hunt button does not. Writing a homemade 20-byte stroke through the hunt device was rejected (`fallback hunt button` in v1.log). The row now calls `Engine/autologin/bot/win/interception.py` `click`, the same function autologin uses. Hunt closes its devices for that click and opens them again afterwards.
Shared: `click_scroll_row` and `_use_talking_scroll` only. `MouseController.click`, hover, the wheel, attack, ground, gate, shop, and the login flow stay on their current paths. If the autologin click cannot run, the row falls back to `move_and_click`.
Affects: the talking-scroll list row. Other clicks stay as they are.
Consent: user (only the scroll row; keep every other mouse path unchanged; hand click and autologin already work).
Result: implemented. Portable `mouse` and `controller` modules rebuilt.

## 2026-10-17 — talking-scroll row uses the login button stroke

Intent: on one 1920x1080 laptop the cursor sits on the talking-scroll row and the wheel scrolls, and the hunt button still does not select the row. That row click now sends the same classic stroke login uses (button in `state`, absolute position), on the first mouse slot that accepts it. The devices already opened for hunt are reused. A second driver context is not opened.
Shared: `click_scroll_row` and `_use_talking_scroll` only. `MouseController.click`, hover moves, the wheel, attack, ground, gate, shop, and login stay on their current paths. If the login stroke cannot be written, the row falls back to `move_and_click`.
Affects: the talking-scroll list row. Other clicks stay as they are.
Consent: user (login stroke for the scroll row only; keep every other mouse path unchanged).
Result: implemented. Portable `mouse` and `controller` modules rebuilt.

## 2026-10-17 — button stroke carries the click pixel

Intent: the relative button stroke still did not select the talking-scroll row on the customer PC. The cursor sat on the row and the wheel scrolled. Login clicks already put the target pixel in an absolute button stroke, and that is the packet this PC accepts.
Shared: `_send_button`, `_click_in_place`, `MouseController.click`, `_click_until_walk`, `hold`. A button release with no pixel uses the current cursor so it does not jump to the origin. Wheel, scroll UV, and login stay as they are.
Affects: talking-scroll rows, ground hops, attack clicks, map gates, and shop clicks.
Consent: user (absolute pixel inside the button stroke, then rebuild `mouse.cp314-win_amd64.pyd`).
Result: implemented. Portable pyd rebuilt after this entry.

## 2026-10-17 — click at the cursor, not at screen origin

Intent: a talking-scroll row click moves the cursor onto the row, then the button packet was an absolute move to (0, 0). On the other laptop the list scrolled and the cursor sat on the row, and the character never left. Button presses now use a relative (0, 0) stroke, the same shape as the wheel.
Shared: `MouseController.click`, `_click_until_walk`, `hold`, `release`, and the button lift in `release_capture`. `move_to`, wheel count, scroll UV, and arrival wait stay as they are. Login clicks stay on `Engine/autologin/bot/win/interception.py`, which already sends the button with the target coordinate.
Affects: talking-scroll rows, ground hops, attack clicks, map gates, and shop clicks. Keys and the wheel are unchanged.
Consent: user (relative button packet in mouse.py for every MouseController click; leave the installed interception package and login path alone).
Result: implemented in `Engine/app/_05_action/mouse.py`. Portable `mouse.cp314-win_amd64.pyd` rebuilt for the customer folder. Not yet tried on the laptop where the row click missed.

## 2026-10-17 — hide the autologin console

Intent: the main program stays windowed, and the autologin child no longer opens a console that sits on screen until login finishes. Purple login, clicks, elevation, and the status file the UI already shows stay the same.
Shared: `AutoLoginService.run` launch only. `bot2` is still `python.exe` with `--no-self-elevate`. When this process is already admin, the child gets `CREATE_NO_WINDOW` and its stdout/stderr go to `UserData/autologin_runs/<id>/console.log`. When it is not admin, the UAC child is `pythonw.exe` with `SW_HIDE`. `bot2_run.log` is unchanged.
Affects: the window the operator sees during Start login. Login steps, shop, movement, combat, and HP are unchanged. The startup UAC prompt for the main program still appears.
Consent: user (hide the autologin console; keep autologin working fully).
Result: implemented. Not yet run against a live Purple login.

## 2026-10-17 — startup memory warm imports on the main thread

Intent: portable ZF.exe was crashing about 0.5s after the admin relaunch because the startup thread imported compiled modules while the main thread was still importing the UI. Elevation, WinNotify start, and the in-process memory attach stay the same call (`warm_memory_at_startup(wait_snapshot=False)` on the `signeddrv-start` thread).
Shared: `prepare_runtime`. The schedule window's later warm is unchanged. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, `apply_inplace_hp_support`, and login clicks stay as they are.
Affects: process start only. The driver and memory reader still start before the operator uses the window. The warm modules are initialized on the main thread first so the worker does not initialize them again.
Consent: user (stop the crash and keep the current startup, workflow, and features).
Result: portable `elevate` module rebuilt. `ZF.exe` stayed up with a window and no access violation.

## 2026-10-17 — member sends player status every 10s

Intent: the member bot connects to the leader address and sends the live player (hp, mp, position, map id, alive, level) every 10 seconds. Follow and combat stay as they are. The leader still farms solo and still sends only critical decisions.
Shared: none. New client start/stop sits next to the leader socket in the worker. The send runs after the world snapshot, before the member decision, and only while member logic is on.
Affects: member websocket traffic and a host field on the party member panel.
Consent: user (client sends current player status with a 10s heartbeat).
Result: implemented.

## 2026-10-17 — leader sends critical solo decisions

Intent: the leader bot keeps the solo farm. It does not run party follow. After a solo decision, teleport, return, talking scroll, gate, shop, and respawn are copied onto the party socket once per change. Attack, loot, heal, and walk ticks are not sent. Member follow is unchanged.
Shared: none. The hook is after `decision.decide` in the bot loop, and only when the role is leader.
Affects: leader websocket traffic. Solo actions stay the ones decide already chose.
Consent: user (verify sending the leader's critical decisions; leader farms solo; only the member uses party logic).
Result: implemented.

## 2026-10-17 — party role selector and leader socket

Intent: the Party tab has two roles, party member and party leader, on both sections. Leader shows this PC's LAN address and the socket port. When the bot runs as leader, the existing party WebSocket server listens on that port until the bot stops. A temporary client window monitors messages and both sides' status. Member follow, assist, loot, combat, retreat, HP, and login are unchanged. Selecting leader turns member follow off so this PC does not also chase a leader.
Shared: none of `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, `apply_inplace_hp_support`. New path is `BotController._start_party_socket` / `_stop_party_socket` around the existing worker. The member gate reads `party_role` and skips member mode when it is leader.
Affects: party tab settings, and a listening socket while a leader bot is running.
Consent: user (party member / party leader select, show IP and port, start the websocket with the leader bot, temporary client UI).
Result: implemented.

## 2026-10-17 — smooth party follow via Reynolds leader-following + Arrive

Intent: travel follow was not smooth — random/exact travel tiles repathing every leader step caused jitter and reverse walks. Replace with Craig Reynolds leader following (GDC'99): formation slot behind the leader with a light lateral flank, Arrive tolerance (hold within 1 tile of the slot), and a sticky absolute goal (keep click target while the ideal drifts ≤2 tiles). HOLD keeps the sticky goal so the next chase reuses it.
Shared: `formation_slot_offset`, `sticky_goal_tile`, `ARRIVAL_TOLERANCE` / `STICKY_GOAL_SLACK`, `FollowField.pick_travel_offset` (formation), manager travel wiring + HOLD sticky keep (all `_06_party`). Assist, settle cardinals, WORLD_NAV, solo, HP, login unchanged.
Affects: party-member travel follow only.
Consent: user ("still not smoothly following, give me the best algorithm. web search… and use").
Result: implemented. Sources: Reynolds steering (leader following / Arrive), formation sticky goal / zLookAhead practice.

## 2026-10-17 — restore contested_mobs capture for party assist (89bd676)

Intent: etview showed the leader's AttackAction target, but the member never assisted. Live `capture_tick` had stopped loading/capturing `contested_mobs.dll` (and `attacks_me`), so `last_contested_mobs` stayed empty. Assist had been rewired to print_state `atk`/`tgt`, which often misses the same row etview sees. Restore the 89bd676 path: init combat readers, capture contested+attacks every tick, prefer contested rows for `leader_attack_rows`, keep print_state as fallback.
Shared: `PerceptionSensors._init_combat_readers` / `capture_tick`, `leader_attack_rows` (contested first). Policy assist gate and resolve-live-only stay as they are.
Affects: party-member assist target discovery (and `last_attacks_me` for strike assist). Solo contested filter still uses print_state. Movement, HP, login unchanged.
Consent: user ("etview shows target… never assist… check 89bd676… at that time it worked").
Result: implemented.

## 2026-10-17 — mage casts only after an attack (knife) cursor like elf

Intent: mage targeting pressed the spell key first and hunted for a `spell` cursor on a cross, so it often clicked empty ground. Elf finds `arrow`/`fist`/`sword` on the monster body ring and clicks. Mage now uses that same ring: hover until an attack cursor is on the body, press the spell key, then click that pixel only when the cursor is `spell`. Miss → reject / Esc, no grind on empty pixels. Elf `attack_click_search` is unchanged.
Shared: `find_attack_aim_point`, `mage_cast_at_point`, `MageCombatStrategy.attack` (mage only). `object_attack_screen_points` is reused read-only.
Affects: mage spell casts. Hunt attack mode ranged/melee for mage still uses elf/knight strategies from the prior change.
Consent: user (knife-first mage aim; do not change elf).
Result: implemented.

## 2026-10-17 — party assist from print_state; mage retarget; mage ranged = bow

Intent: (1) Party farm assist was not attacking the leader's monster. Assist read `last_contested_mobs`, but the live tick never fills that DLL snapshot — contested claims for solo already come from print_state `atk`/`tgt`. Assist now builds the leader's target from the same print_state Player AttackAction, with the DLL as a fallback only. Policy assists when that target is resolved inside the assist leash, even if the old `leader_farming` flag is late. Assist also runs with a party-guid proxy when the leader entity is off-screen. Soft give-up / blacklist ids are skipped so a failed cast can retarget. (2) Mage casts that miss the cursor used to Esc and re-aim the same sticky target without `mid_act`, so every tick re-pressed the skill and clicked the same area. Party ASSIST/DEFEND now set `mid_act` while the assist track_id is unchanged; after `CURSOR_VERIFY_FAIL_GIVE_UP` cursor rejects the blackboard give-up is honored and assist picks another monster. (3) Hunt Attack mode was stored in the UI but ignored by combat. Mage + `magic` keeps spell cast; mage + `ranged` uses the elf bow strategy; mage + `melee` uses knight clicks. Spell-range filters and mage MP-cast probes apply only when `uses_spell_aim()` is true.
Shared: `leader_attack_rows` / strike resolve (print_state), `pick_assist_target` (blackboard exclude), party policy assist gate, `attack(..., mid_act)`, `player_mode.ATTACK_MODE` / `uses_spell_aim`, `combat_strategy_for(attack_mode)`, combat_query/target_selector spell-range gates, profile `attack_mode`, task_runtime + ActionExecutor wiring. Solo farm, retreat, HP, and login stay as they are aside from the spell-range gate when attack mode is not magic.
Affects: party-member assist and farming; mage (and only mage) combat strategy and target range when Attack is Ranged/Melee/Magic.
Consent: user ("must retarget… farm as range with bow… check deeply assist… contradiction… check and fix").
Result: implemented. Print_state leader atk→monster resolves to `leader_attack`; policy returns ASSIST without `leader_farming`. Files compile. Full combat_strategy import was not run here (this Python has no numpy).

## 2026-10-17 — party member farming method: solo farm / party farm

Intent: the Party tab has a "Farming method" choice. Party farm (default) is the existing logic: the member only attacks what the leader attacks or strikes. Solo farm keeps the same follow and stop logic, but the member picks its own nearest target. It uses the solo `list_attackable` gates: species allow/deny, monsters claimed by another player, line of attack, mage range, and the give-up/blacklist set. The target must be within `assist_leash_tiles` of the leader and on screen. The member keeps its target while it is alive and in range, and fights it whether the leader is fighting or not. When the leader walks past the leash, follow wins. Solo farm loots its own drops (ownership gate on) within `follow_tiles` of the leader, including during fights. A pickup walk in progress is not cut by the stand/spot re-follow until the leash breaks.
Shared: `PartyMemberConfig.farm_mode`, `pick_solo_farm_target`, `PolicyInput.solo_farm`, `party_loot_ownership_filter` (solo → own drops), and the manager loot gate (all in `_06_party`). Profile `party_farm_mode`, settings bag, `task_runtime`, schedule export, and the `bot_controller` config build. Solo `_04_decision` is read only (`list_attackable`, `excluded_target_ids`, `is_avoided_for_state`). `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login stay as they are.
Affects: party members in solo farm mode only. Party farm decisions and loot gates are unchanged. In solo farm, the Party loot random/role controls are disabled because they do not apply.
Consent: user ("implement solo farm / party farm selection … party mode is current logic").
Result: implemented. Checks pass. Config normalizes to party/solo. In solo, with the leader idle and a target in the leash, the result is ASSIST (or CLOSE_IN when out of range). Past the leash it is FOLLOW. Party mode with the same input still follows. The profile round trip works. The Qt tab compiles; it was not run here because PySide6 is missing from this Python.

## 2026-10-17 — party member travels on a random side of the leader

Intent: the member no longer trails behind a walking leader. While the leader walks, the member keeps one random tile around the leader as an offset that moves with it. The tile can be on any side and within `follow_tiles − 2` walk steps (2 at F=4). The member walks to that tile and holds on it. Each leader step moves the tile, so the member moves with the leader at once. A new random offset is picked each time the leader starts walking again, or when the tile is blocked, occupied, or has no path. The stopped stand is unchanged: random up, down, left, or right at S walk steps.
Shared: `FollowField.pick_travel_offset`, `travel_band`, `follow_kind(at_travel_spot)`, `PolicyInput.at_travel_spot`, `plan_follow_intent(stand_reason)` (all in `_06_party`). Solo code, combat, the HP path, login, and UI stay as they are.
Affects: party member travel follow. The walk-path click (`plan_field_follow`) is now only used when no spot is free around the leader. Combat assist, the combat leash, and world-nav stay as they are.
Consent: user ("member bot don't need to be behind of leader, move and stop around randomly").
Result: implemented. Checks pass. With F=4, offsets cover all 8 sides within 2 steps. A valid offset is kept, and a blocked one is re-rolled. The policy follows until the member is on the spot, then holds.

## 2026-10-17 — party member follow and stop use walk steps

Intent: the member's follow (`follow_tiles`) and stop (`stop_tiles`) bands count real walk steps to the leader, not Chebyshev distance. A wall or body between them no longer reads as "close". One bounded reverse BFS from the leader tile (`follow_field.py`) gives the member's steps and the path down to the leader. Travel clicks pick a hop on that path with `select_click_waypoint`, with no A*. The field is cached by leader tile, window, terrain, and nearby bodies. Window radius is `2×F+2` (min 8, max 24). Measured cost is about 1 ms at F=4 and about 5.6 ms at the cap. A cache hit costs under 1 µs.
Shared: `build_follow_field`, `FollowFieldCache`, `plan_field_follow`, `pick_settle_stand` (field filter), `PolicyInput.leader_walk_dist` (all in `_06_party`). The pathfinding code is read only (`select_click_waypoint`, `waypoint_to_content`, `TerrainMap.can_step`). Solo `_04_decision`, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login, and UI stay as they are.
Affects: party member travel and settle only. The combat leash, assist, close-in, world-nav route choice, and the loot gate keep Chebyshev. A member that is unreachable inside the window counts as past the window, and its click falls back to the old A* follow. A settle stand must be within S walk steps. While a click is still more than 1 tile away, the member does not click again until the goal moves.
Consent: user ("implement walkable distance following only for this member bot").
Result: implemented. Checks pass. Through a wall the Chebyshev distance is 4 but the walk is 12 steps, and the member follows around the wall end. Tiles behind a body in a 1-wide corridor are unreachable. On open ground, walk steps equal Chebyshev distance.

## 2026-10-17 — party member keeps the follow distance and settles beside the leader

Intent: while the leader walks, the member stays within `follow_tiles` (UI F). It starts chasing 2 tiles before F (`TRAVEL_LEAD_TILES`) and keeps walking while it is farther than `stop_tiles`. Before this change it waited until it was already past F, so the 1–2 s reaction lag let the gap grow past F. When the leader stops (0.7 s settle, unchanged), the member picks one random tile up, down, left, or right of the leader at distance `stop_tiles` (UI S). It keeps that tile until the leader moves again. The old behavior stood on whichever tile was nearest the member, which meant behind the leader.
Shared: `follow_kind`, `choose_settle_stand`, `pick_settle_stand`, `plan_follow_intent`, `PartyMemberManager._update_settle_stand` (all inside `_06_party`). Solo `_04_decision`, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login, UI, and party sensors stay as they are.
Affects: party member follow only. Combat assist, the combat leash, join-map, world-nav follow, and loot gates are unchanged. If a stand is occupied, the member picks another one. If a stand has no path, it is blocked until the leader moves. If no cardinal tile is walkable, the member falls back to the `stop_tiles` radius.
Consent: user ("implement", after the scope was limited to `_06_party`).
Result: implemented. Pure checks pass: with F=4 and S=1, travel chases at a distance of 2 or more. The settle stand is always one of the four cardinal tiles, and it stays locked unless occupied.

## 2026-10-17 — avoidance uses the memory monster class

Intent: movement avoidance treats a print_state `Monster` or `SummonedMonster` as a body even when the species filter typed it OTHER. Attack, loot, and target selection keep the species filter.
Shared: `collect_body_tiles`. Handoff `classification` is stored as `memory_class`. `object_type_from_classifiers` stays as it is.
Affects: travel, search, and loot hops, and the click-line check. Players and NPCs still use object type. The blacklist still only blocks attacks.
Consent: user (memory class for avoidance only; keep species identification everywhere else).
Result: implemented. An uncatalogued memory monster stays OTHER and is still an avoid tile. A resolved species stays MONSTER.

## 2026-10-17 — page-cache readers installed in this tree

Intent: bring the memory-project readers into this tree and rebuild the DLLs the bot loads. Decision, movement, combat, and HP action code stay as they are.
Shared readers: `pgcache.h`, `print_state.c`, `realtime_monitor_full.c`, `inventory_listen.c`, `hotbar_listen.c`, `nametable.c`, `shop_listen.c`, `lcore.h`, `buff_listen.c`, `uidialog_listen.c`.
Consent: user (apply the memory-project read changes together and rebuild).
Result: sources match that tree. DLLs rebuilt and loaded. Live snapshots returned print_state 13 entities at player (33457, 32782) HP 119/157, monitor the same pose with mapId 4, inventory 43 named items, hotbar 24 slots, buff 2, uidialog 5 windows. Shop subsystem was found; buy and sell lists were empty while the shop window was closed.

## 2026-10-17 — one-snapshot page cache on the live readers

Intent: cut driver calls inside one snapshot. The same bytes are still read every tick. Owner/target, fast PRES, bag counts, buff remain, UI open state, and map id stay live. The nested PRES child walk is gone; a slot vft or that object's +0x10 still resolves PRES.
Shared readers: `pgcache.h` under `rm`/`readMem` in `print_state.c`, `realtime_monitor_full.c`, `inventory_listen.c`, `hotbar_listen.c`, `nametable.c`, `shop_listen.c`, `lcore.h` (buff and uidialog). Subsystem vft reuse on the actor grid, bag, hotbar, and shop. `$id` strings are remembered after the first resolve. Inventory heap name scan and `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: how many IOCTLs a tick spends. Decision fields, tick order, and poll clocks are unchanged. A PRES that existed only behind a child pointer no longer gets coordinates.
Consent: user (minimize IOCTL without changing decision performance; the per-call leftovers in the monitor, bag, and buffs are in scope).
Result: implemented in the readers above.

## 2026-10-16 — mage cast clicks the center of the spell range

Intent: after the mage spell key, probe a screen cross through the monster and click the midpoint of the pixels whose cursor is `spell`. A locked fight reuses that center while it still reads `spell`. `spell_disable` and `spell_out_range` stay rejected.
Shared: `mage_spell_cross_points`, `spell_range_center`, `mage_cast_click_search`, `MageCombatStrategy.attack`. The cross is centered on the same 0.2-screen-up body point as melee, with arms at 0.40 and 1.10 screen tiles. `object_attack_screen_points`, knight/elf/royal clicks, loot, travel, retreat, and HP stay as they are.
Affects: mage attack casts. One cast hovers the cross (about 0.2 s) before the click, inside the 0.50 s cast gap. A `spell` pixel past a non-spell gap is left out, so a neighbor on an outer arm does not pull the center. A cast with no `spell` pixel still cancels with Esc. A monster that walks off the locked center is measured again.
Consent: user (go, after the mage spell-center proposal).
Result: implemented.

## 2026-10-16 — paused schedule update reaches the running logic

Intent: Alt+A pause, then "update schedule", copies that schedule onto the live profile and the worker re-applies the Start configure path before the next decision tick. Resume uses the new settings. A running bot still does not apply. Map, routine, or farm-list changes restart the routine cursor and the in-farm timer. Stay-time and HP edits keep that timer.
Shared: `publish_paused_task`, `install_profile_runtime`, `restart_paused_routine`, `_consume_paused_settings`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, `apply_inplace_hp_support`, and login clicks stay as they are. Account, character class, the memory monitor, and the perception capture still change only on stop/start.
Affects: hunt, travel goal, return, loot, shop restock, HP potion/heal/escape thresholds, teleport, farm rotation, and routine after a paused update. The character stays where they are. A route change makes the next resume walk the new goal.
Consent: user (apply paused schedule updates to the running logic; keep account, class, and capture on stop/start).
Result: implemented. Qt and classic "update current" both publish while paused.

## 2026-10-16 — dungeon cursor lock requires a clear line

Intent: a dungeon world-nav attack cursor locks the monster under the probe only when the straight line is clear. A line that blocks later releases that lock with the existing dungeon wall skip, without a give-up cooldown.
Shared: `monster_under_travel_cursor`, `cursor_engage_target`, `continue_or_start_combat` dungeon-wall skip. The nearest monster stays the cursor target; a blocked line does not substitute another monster within 3 tiles. `can_engage_target` on the normal list, attacks_me, path cap, field wall detour, and travel clicks that need a normal cursor stay as they are.
Affects: dungeon hunting during a world-nav walk. A fenced sprite no longer keeps the attack clicks. A clear-line cursor lock still fights ahead of ground loot. One-tick line flicker can drop the lock and allow one ground hop before screen combat reselects.
Consent: user (apply the proposed gate; check it does not disturb other dungeon attack paths).
Result: implemented.

## 2026-10-16 — stay on the goal dungeon floor

Intent: when the hunt goal is a dungeon floor, the planner does not expand a transition whose destination map differs once the search node is already on that floor. Entering the floor, and ladders used while the node is still short of the goal floor, stay.
Shared: `WorldNavPlanner.plan` transition expansion. `Transition.from_floor` / `to_floor` copy the cell `floor`. Gate circle, NPC teleporter settle, scroll, combat, retreat, HP, and login stay as they are.
Affects: world-nav plans whose goal map is a dungeon floor. A same-floor point goal no longer detours through the next floor via a ladder beside the entrance. A deeper-floor goal still climbs. A retreat whose goal is town can still leave. If the entrance and the patrol are not connected by a walk on that floor, the plan fails.
Consent: user (dungeon movement only; cover the same detour in other dungeons; do not collide with other logic).
Result: implemented.

## 2026-10-16 — dungeon hunt walk locks the monster under the attack cursor

Intent: a Talking Island dungeon world-nav hop whose probe shows an attack cursor stops the ground-click ring and fights that on-screen monster until the existing sticky release. A blocked terrain line does not drop this lock.
Shared: `ActionExecutor._search` / `_arm_dungeon_cursor_engage` (reason `world nav walk` and dungeon only). `monster_under_travel_cursor`, `farm_loot_or_combat` cursor branch, `continue_or_start_combat` dungeon-wall skip. `can_engage_target` still filters the candidate list. `travel_click` still requires a normal cursor. Shop, return, field walks, `arrow_lack`, contested, blacklist, and give-up cooldown do not arm the lock.
Affects: dungeon hunting while a world-nav walk is in progress. Ground loot waits until that kill ends. Field wall detour, patrol, and shop travel keep sliding off an attack cursor.
Consent: user (analyze conflicts, then implement this handoff).
Result: implemented.

## 2026-10-15 — attacks_me reads the entity cell, not a (0,0) placeholder

Intent: an attacker row carries the same world cell print_state reads from the entity. A failed read omits `world` instead of publishing cell (0, 0).
Shared: `attacks_me.c` `readEntCell` / `pushActor` / `emitActorTail`. Offsets `off_ent_cell_x` / `off_ent_cell_y` come from `settings_print_state.json`. `sync_attacks_me_force_targets` only gained a cell log; match, sticky, LOS, and ring click are unchanged.
Affects: which monster `attacked_me` latches onto. A row with no cell is skipped by the existing missing-world path.
Consent: user (fix the cell read in attacks_me only; do not filter the symptom in combat).
Result: implemented. `attacks_me.dll` rebuilt after this source.

## 2026-10-15 — memory reads follow dist batching, this project's clocks

Intent: cut repeated driver reads of the same bytes. Fixed anchors, one-block field reads, vft subsystem cache, action-block fingerprints, and pointer chunks. Tick timing, HP, pose, map id, and print_state fast PRES stay on every call. attacks_me and contested structure sweeps use the print_state roster clock (100ms, or a move over 8 tiles) and return the previous JSON in between.
Shared readers: `realtime_monitor_full.c`, `lcore.h`, `lbuff.h`, `attacks_me.c`, `contested_mobs.c`, `print_state.c` `findPres`, `uidialog_listen.c`. Decision, movement, combat, and HP action code stay as they are.
Affects: live memory reads. Attack and contested lists can be up to 100ms old. The monitor DLL does not start the 64KB heap scan, so its `entities` array is empty; clicks still come from print_state. Buffs come from `BuffListBase`.
Consent: user (apply only the call reductions; keep this project's timing; reconsider locking the entity sweep to the decision tick).
Result: implemented. Canon: `Docs/architecture/MEMORY_READ_CANON.md`. DLLs rebuilt.

## 2026-10-15 — ignore named adena at or below a UI qty

Intent: when the schedule loot checkbox is on, named adena with loot_qty <= the entered value is not approached. Unnamed piles are not subject to this gate. Adena already within pickup range is still F4'd, including side pickup. Default is off, and the spin shows 10.
Shared: `small_adena_ignored`, `list_lootable` (main path only), loot sticky when out of range, pending re-approach.
Affects: loot approach in hunt, retreat, and farm entry. Feet F4, combat aim, retreat movement, login, and HP stay as they are.
Consent: user. Procedure: `D:\md\pending_specs.md` section 2, plus the later feet-F4 and unnamed-name amendments.
Result: implemented. `Others/tests/test_ground_loot.py`.

## 2026-10-15 — main loot contrib floor is 50

Intent: main-intent MINE loot requires contrib above 50. 50 is rejected, 51 is allowed. FREE and side F4 are unchanged.
Shared: `LOOT_CONTRIB_MIN`, `loot_ownership_allowed`.
Affects: hunt main-intent approach and pickup. Combat, retreat, login, and HP stay as they are.
Consent: user. Procedure: `D:\md\pending_specs.md` section 3.
Result: implemented. `Others/tests/test_ground_loot.py`.

## 2026-10-15 — attack aim starts 0.2 tiles screen-up

Intent: the attack cursor's first point and the 0.1-tile ring center move from the iscr feet point to 0.2 tiles screen-up. Ring radius, cursor pass score, and give-up rules stay as they are.
Shared: `content_screen_up`, `object_attack_screen_points`, `ATTACK_AIM_SCREEN_UP_TILES`.
Affects: knight, elf, and mage attack aim. Loot clicks and movement clicks stay as they are.
Consent: user. Procedure: `D:\md\pending_specs.md` section 1.
Result: implemented. `Others/tests/test_attack_cursor_search.py`.

## 2026-10-14.8 — search hops use plan_body_click + 0.1s reclick

Consent: user asked for phase 1+2 on search hops only.

Intent: farm search keeps ``next_leg`` coverage goals; each hop click uses ``plan_body_click``. Standing body re-clicks the hop ~0.1s (``classify_ground_reclick``). Coverage visit counts on ``search_leg_goal`` arrival.

Shared: `emit_search_hop`, `plan_body_click`, `collect_body_tiles`, blackboard `search_leg_goal` / `search_click_at`.

Affected: farming SEARCHING hops only. Travel/loot/combat unchanged. LEG_TICKS / unstick timers unchanged.

## 2026-10-14.7 — until_walk re-clicks re-check cursor

Consent: user agreed to apply cursor verify on until_walk re-clicks.

Intent: after a NORMAL travel hop verify, mid-loop re-clicks must not fire if the cursor becomes attack/dialog. Stops further clicks with `how=cursor`. Pose-pulse unchanged.

Shared: `MouseController.click(cursor_ok=...)` / `_click_until_walk`, `verified_click` gate for `until_walk`.

Affected: SEARCHING / TRAVELING / loot-approach / unstick ground hops via `travel_click`. Attack/loot single clicks unchanged.

## 2026-10-14.6 — remove ground-click until_walk budget

Consent: user asked to remove only the 0.4s budget.

Intent: restore 10/11 contract — ground hops keep clicking until body stand/walk (or unread 1s). The 10/14 `GROUND_CLICK_BUDGET_S=0.4` early exit caused post-kill search holds with no walk started. Pose-pulse during execute stays.

Shared: `MouseController._click_until_walk` only.

Affected: SEARCHING / TRAVELING / loot-approach / unstick ground hops. Attack clicks unchanged. Execute pose-pulse unchanged.

## 2026-10-14.5 — field map hygiene (no accidental edge wipe)

Consent: user asked to remove traps from the TI/mainland map cleanup audit.

Intent: refuse PNG-only prebuild on packs that already have `edge_*.npy`; document `Build_Field_Edge_Packs.bat` as the only field rebuild; quarantine stale `Others/maps` TI/mainland images; field-view downsample uses majority vote; `is_game_walk_clear` uses `can_step` so fence edges close client polylines on travel-click paths too.

Shared: `build_nav_prebuild.py`, `is_game_walk_clear`, `field_terrain._kinds`, Support README, Others TI/mainland `legacy/`.

Affected: field rebuild ops, field-view wall dots, `select_click_waypoint` / travel clicks that use `is_game_walk_clear`. ActionExecutor unchanged.

## 2026-10-14.4 — field travel uses body-avoid hop (plan_body_click)

Consent: user agreed to apply the same guide→interim→hop plan as dungeon patrol / ti_edge_nav to general field `emit_travel_hop`, without changing ActionExecutor or cursor search.

Intent: every travel hop always calls `plan_body_click` (empty bodies when `state` is missing). Patrol-only `skip_blocked_patrol_point` on no-click; other purposes hold + IDLE and retry. `click_clear` / avoidance BFS use `terrain.can_step` so field N/E fences close the client polyline.

Shared: `_follow_body_click` / `emit_travel_hop`, `click_clear`, avoidance `_bfs`.

Affected: field travel, enter-farm, shop walk, world_nav walk. Patrol/loot already on the same API. Cursor search, reclick timers, unstick 360° unchanged.

## 2026-10-14.3 — body action vfts for the 10.14.2 client

Consent: user asked to match every RVA used to detect the character's action to the current patch.

Intent: `ActionComponent+0xC0` and `ActorController+0x58` class RVAs follow live RTTI. Walk is `MovingAction` `0x11E0590`, walk-back `0x11E0548`. Turn, spell, pickup, shop, commands, and the other body labels move with them. Stand, attack, death, damaged, and effect were already on this image. Decision branches are unchanged.

Shared: `body_pose.py` `BODY` / `CMD` / `MOVE_VFTS`, registry action keys, `action_timeline.py`, `interact_watch.py`, `probe_my_anim.c`.

Affected: action view, `body_is_moving`, ground-click stop, travel reclick, loot hop hold.

## 2026-10-14 — LOS blocked by N/E fence edges between open tiles

Consent: user agreed that attack LOS must fail when neighboring open tiles on the segment cannot step across a fence.

Intent: `line_of_sight_clear` still requires intermediate walkable cells, and now also requires an open shared edge (`_los_step_open` / bit0 N/E) between every consecutive segment pair. Goal tile may stay non-walkable; the edge into it is still checked.

Shared: `line_of_sight_clear`, `_los_step_open` → `attack_line_clear`, dungeon/field engage filters that use it.

Affected: target selection when a fence sits on the Chebyshev LOS polyline.

## 2026-10-14 — LOS blocked by N/E fence edges between open tiles

Consent: user agreed that attack LOS must fail when neighboring open tiles on the segment cannot step across a fence.

Intent: `line_of_sight_clear` still requires intermediate walkable cells, and now also requires an open shared edge (`_los_step_open` / bit0 N/E) between every consecutive segment pair. Goal tile may stay non-walkable; the edge into it is still checked.

Shared: `line_of_sight_clear`, `_los_step_open` → `attack_line_clear`, dungeon/field engage filters that use it.

Affected: target selection when a fence sits on the Chebyshev LOS polyline.

## 2026-10-14 — TI/mainland fence_bw packs + edge portal prebuild

Consent: user asked to replace Talking Island and mainland map packs with fence_bw_4x display, prebuild portal graphs like ti_edge_nav (`can_step`), keep `.s32` only under `Support/field_s32` (not shipped), and defer avoidance-hop transplant. map_4 coverage is sufficient.

Intent: Deployable packs ship `*_fence_bw_4x.png` + `nav_prebuild` (including optional edge npy). Fine A* / portal neighbors use N/E fences when edge layers are present. Dungeon packs unchanged. Body-avoid hop policy unchanged.

Shared: `edge_layers`, `TerrainMap.can_step` / `block_n`/`block_e`, `build_portal_graph`, `build_and_save_edge_prebuild`, `Tools/nav/build_field_edge_packs.py`.

Affected: talking_island and mainland travel pathfinding and map-editor/debug terrain image. `.s32` rebuild input only in Support.

## 2026-10-14.2 — client rebuild read addresses

Consent: user said the client was patched again, `D:\dist` was replaced, and this project's memory reads should follow it.

Intent: RVAs and vfts move to registry v9 (`MODULE_SIZE` 0x3F5F000, globals +0x10, RTTI rebind). Structure offsets and poll periods stay.

Shared readers: registry, `char_offsets.txt`, `entity_offsets.txt`, inventory/hotbar files, `offsets.json`, `body_pose.py` (stand/attack/death/effect), `shop_listen.c`.

Affected: live reads. Walk/turn/spell/command vfts are not in the new registry; those body labels stay on the previous image. Decision logic is unchanged.

## 2026-10-14 — avoid radius 10 + farthest guide hop click

Consent: user asked to set the avoid window to 10 tiles, and to check/fix dungeon movement still clicking only Chebyshev neighbors.

Intent: `AVOID_RADIUS` 7→10 (21×21 window). When the interim waypoint fails hop/clear, `choose_body_click` keeps the **farthest** legal guide tile inside `max_hop`, not the first neighbor. Empty-body `plan_avoidance_click` also requires hop/region/clear before returning the waypoint.

Shared: `AVOID_RADIUS`, `plan_avoidance_click`, `choose_body_click`, `_farthest_guide_click`. Dungeon patrol/travel/loot that call `plan_body_click`.

Affected: avoidance hop distance and body window. Field travel that still uses `plan_travel_click` / `select_click_waypoint` is unchanged (already farthest). Tool `ti_edge_nav` imports the same radius.

## 2026-10-14 — 10.14 client read addresses

Consent: user asked to replace this project's memory read addresses with `D:\dist` after the client update, and to leave bot logic and poll periods alone.

Intent: module RVAs and vft values move to the 2026-10-14 registry. Structure offsets (`MapIdOff` 0x718, holder/subs, PRES_B, stat decode) stay. Poll intervals stay.

Shared readers: registry, `char_offsets.txt`, `entity_offsets.txt`, inventory/hotbar offset files, `offsets.json` map vft, `body_pose.py` action vfts, `shop_listen.c`.

Affected: live memory reads (map, player, entities, HP, buff, UI, hotbar, inventory, shop). Decision, movement, and combat branches are unchanged.

## 2026-10-14 — dead source actors still mark a drop OTHER

Consent: user asked the bot loot claim to follow the etview result, using only this project's code.

Intent: a zero-contrib pile is OTHER while a source actor whose guid sits within the last-hit window is still in the sweep, including a corpse. Dead actors are kept for that test and left out of the JSON roster. FREE or contrib above 30 is unchanged.

Shared: `print_state.c` sweep retention and JSON emit. Live monster and item lists stay the same.

Affected: `own` on a pile whose source body is still in memory.

## 2026-10-14 — log item claim when loot is chosen

Consent: user asked to record item state when a pile is chosen, so the next log can be analyzed.

Intent: one `loot decide` line with name, guid, own, contrib, and whether the main ownership gate would allow it. Selection rules are unchanged. Side F4 logs `gate=skip` and does not repeat the same id and claim every tick.

Shared: `begin_loot_item`, `arm_loot_side_intent`.

Affected: loot log only.

## 2026-10-14 — skip other players' monsters by guid

Consent: user asked to match contested mobs by id, not world cell.

Intent: a new engage drops a monster only when contested `guid` equals `memory_guid`. A monster with no guid stays eligible. World cells are not a claim.

Shared: `contested_mob_guids`, `is_contested_monster`, `list_attackable`, `describe_attackable_filter_skips`. Sticky combat and attacks-me force still bypass this list.

Affected: new targets chosen by `nearest_attackable` on farm and in dungeons.

Result: implemented. `test_attack_filter.py`. Confirm on the next bot log line `contested guid filter`.

## 2026-10-14 — skip a patrol point after 10s with no click

Consent: user asked to leave a patrol midpoint when a guide exists but living bodies leave no click for 10 seconds.

Intent: the clock starts on the first such plan for that midpoint. A click, a missing guide, or a new goal clears it. At 10 seconds the next midpoint becomes the travel goal. A missing terrain path still uses the old failure path.

Shared: `emit_travel_hop` for patrol, `skip_blocked_patrol_point`. Loot, field travel, and combat selection are unchanged.

Affected: dungeon patrol only, and only while the click cannot be chosen.

## 2026-10-14 — dungeon loot path 15, ignore blacklisted attackers

Consent: user asked for both dungeon-only changes.

Intent: a new dungeon loot pick requires an A* route of at most 15 steps. Combat new picks stay at 30. In a dungeon a species-blacklisted monster that attacks is not engaged and an existing lock on that species is dropped. Outside dungeons the attacks-me bypass stays.

Shared: `list_lootable` path cap, `list_attacked_me_targets`, `nearest_attacks_me_force`, `continue_sticky_combat`. Field loot Chebyshev cap and field self-defense are unchanged.

Affected: which piles a dungeon walks to, and whether a blacklisted species pulls the character into a fight.

## 2026-10-14 — dungeon patrol and loot walk around living bodies

Consent: user agreed the patrol/loot scope, then set the loot goal to the pile tile and required a 0.1s reclick while the body is not walking.

Intent: dungeon patrol and loot approach use the interim waypoint and the avoidance click. The hop still arrives at the click tile. A body that is not walking gets that same click again every 0.1s. No safe click waits and retries; a missing terrain path still uses the old failure path.

Shared: `plan_body_click`, `emit_travel_hop` when purpose is patrol, `tick_loot_item` walk. `plan_travel_click` stays for field travel, shop, retreat, and unstick. Combat and loot choice order is unchanged. Pickup range is unchanged.

Affected: dungeon patrol clicks and the walk onto a loot pile. A blocked click no longer waits 2s on those two walks.

## 2026-10-13 — a diagonal gap stays open unless both shoulders are walls

Consent: user stated the client rule. Two living bodies, or a living body beside a real wall, do not close the diagonal. It closes only when both shoulders are real walls.

Intent: avoidance clicks and the window search use the same shoulder test as terrain `diagonal_open`. Stepping onto a living body or a wall is still refused.

Shared: `click_clear`, avoidance `_bfs`. Travel hop selection does not call these. `is_game_walk_clear` and `select_click_waypoint` are unchanged.

Affected: avoid-view click choice when a shoulder is a living body. A tile with a living body on it is still not a click.

## 2026-10-13 — ground click walks the diagonal, then the axis

Consent: user confirmed on the client that the walk is diagonal first in tile coordinates, then the leftover axis, and asked to update every dependent check.

Intent: `game_client_walk_tiles` emits that order. Equal `|dx|` and `|dy|` stay a pure diagonal. `(0,0)→(5,2)` is `(1,1) (2,2) (3,2) (4,2) (5,2)`.

Shared: `is_game_walk_clear`, `is_click_valid`, `click_clear`, avoidance clicks, and the avoid-view orange line.

Affected: which travel hops are allowed, and loot or combat ground-click clearance. Attack range still uses the straight line.

## 2026-10-12 — recast Teleport to Mother until the World Tree blessing

Consent: user agreed the plan, then added that recovered HP ends the retreat even when the blessing is still absent.

Intent: one Teleport to Mother press is not arrival. While this retreat is open and HP is under 95%, a buff read 2 seconds after the press with no 세계수의 가호 (strId 993) presses the skill again if MP can pay the 10 cost. MP below that waits. An untrusted buff snapshot waits. HP at or above 95% leaves without the aura.

Shared: `_tick_mother_tree_retreat`, `_hold_until_world_tree_blessing`, `world_tree_blessing_active`, `finish_retreat` (drops `mother_tree_cast_at`). Every mother-tree entry already uses this tick: HP-threshold retreat, post-land, teleport fallback, post-respawn, dungeon GUI.

Affected: standing at the tree before the aura is confirmed. Heal and Body to Mind run after the blessing is on, or after the skill can no longer be used. Shop, `begin_retreat`, buff read, and the key press are unchanged.

Live result: unit tests. Needs a bot restart.

## 2026-10-12 — sticky yields to a monster that has attacked me

Consent: user asked to implement the agreed attacked-me latch. A monster that has once attacked stays latched after the attack row drops. Sticky switches immediately when it has not attacked me, or when a latched monster has a lower known level.

Intent: `attacked_me` is set from `attacks_me` and cleared on death, bait, list removal, or a MapSubsystem mapId change. Synthetics that exist only for the current attack row still end when that row ends. Same level keeps the current sticky. Unknown level ranks after every known level. The previous target is not given up.

Shared: `sync_attacks_me_force_targets`, `prefer_attacked_me_sticky`, `begin_engage`, `rebind_sticky_target`, `note_attacked_me_map`.

Affected: farm engage, travel engage, and world-nav walk combat. Heal still waits while the new sticky is alive. Loot still waits while that lock is held.

Live result: unit tests. Needs a bot restart.

## 2026-10-12 — HP retreat sells first when weight is at least 50%

Consent: user asked to sell before an HP-threshold retreat when the weight gauge is at least 50%, and to retreat immediately when it is below 50%.

Intent: the retreat decision checks weight once. At or above 50%, the existing sell queue runs, and the HP retreat starts when that queue ends. Below 50%, an open shop trip is dropped and retreat starts on that tick. Exactly 50% sells first.

Shared: `apply_hp_actions`, `clear_shop_trip`, `arm_sell_before_hp_retreat`. While that sell is running, HP retreat and heal do not take the tick. Death drops the pending sell and uses the respawn retreat. The 70% overweight sell while HP is still above the retreat gate is unchanged. MP retreat, idle return, and post-respawn retreat do not use this weight check.

Live result: unit tests. Needs a bot restart.

## 2026-10-12 — heal is decided only in decision, and waits out an attack

Consent: user asked to fix the heal filters that action was refusing, and to hold heal while the character is attacking.

Intent: action presses a heal key it was given. The MP 20% reserve no longer drops heal. Mother-tree MP, the heal slot switch, and a missing hotbar cell stay in decision. A living sticky target blocks heal until that target is dead or the lock is gone.

Shared: `emit_heal`, `maybe_heal_after_teleport`, `heal_press_slot`, `_can_heal_now`, `ActionExecutor._press_assigned_skill` / `_heal`.

Affected: hunting, retreat, and post-teleport heal. Retreat threshold and HP potions are unchanged. Other spells still keep their action-side mana checks.

Live result: unit tests. Needs a bot restart.

## 2026-10-12 — shops.yaml removed

Consent: user said the stall list can be deleted.

Intent: merchant places, dialog clicks, warehouse, and teleporters stay in `Engine/data/npc_behaviors.yaml`. `Engine/data/maps/shops.yaml` is gone, and nothing writes it back.

Shared: `tick_shop_trip` (a missing behavior id clears the trip), `seed_behaviors` (no longer reads a stall list). Shop List editor removed with the file.

Affected: arrow recover travel that used the stall list. Buy, sell, warehouse, and teleporter trips that have an NPC behavior are unchanged.

Live result: file deleted. Needs a bot restart.

## 2026-10-12 — NPC catalog leaves the maps folder

Consent: user asked to move the shopping catalog out of map-folder replaces and rename it, because it holds buy, sell, warehouse, and teleporter behaviors. The restored file stays as-is.

Intent: live load and every editor save `Engine/data/npc_behaviors.yaml`. A missing file is copied once from `Engine/data/maps/shopping_behaviors.yaml`, then from `UserData/shopping_behaviors.yaml`.

Shared: `shop.behaviors.BEHAVIORS_PATH`, Shopping Practice, NPC click-offset calibrator.

Affected: shop, sell, warehouse, and teleporter trips read the new file. Trip choice, clicks, and HP are unchanged.

Live result: the restored catalog (32260 bytes) was moved. Needs a bot restart so the new path is loaded.

## 2026-10-12 — weight gate uses the decoded percent

Consent: user confirmed 0x300 is the current weight percent and told us to use it for the weight gate. The plain pair at 0x3AC/0x3B0 stays on screen only.

Intent: sell and adena-only loot compare `inventory.weight_ratio`, filled from decoded WEIGHT (0x300) / 100. A noisy cur/max pair cannot open or block that gate.

Shared functions: `bag_weight_ratio`, `player_from_snapshot`, monitor `weightPct`.

Affected: sell trip (70% default), adena-only loot (30% default). Retreat, combat, and HP are unchanged.

Live result: needs a bot restart so the new monitor DLL is loaded.

## 2026-10-11 — every ground click repeats until the walk starts

Consent: user confirmed the scope. The post-kill arm is removed because it also caught the next attack click.

Intent: a ground hop repeats every 0.1s while the body is busy, and stops when the body stands or walks. Search, travel, retreat, unstick, and the walk up to a pile all go through `travel_click`.

Shared functions: `travel_click`, `Mouse.click(until_walk=True)`. `clickgap` only records again.

Unchanged: attack, gate, shop, talking-scroll row, death-screen restart, F4, login. One click when already standing or walking. Unreadable body stops after 1s.

Live result: unit tests updated. Needs a bot restart.

## 2026-10-11 — an attack is blocked only by the straight line

Consent: user confirmed the scope. The client walk polyline is not an attack gate.

Intent: a monster is attackable only when the straight line to it has no blocked tile between the two, and the monster is inside click range. Field and dungeon use that same rule.

Shared function: `can_engage_target`. `list_attackable` and sticky combat call it. A blocked line on the field falls through to the existing wall detour. Dungeon sticky release is unchanged.

Unchanged: travel, search, and loot still use `is_game_walk_clear`. The dungeon new-target path-length cap stays.

Live result: unit tests updated. In-game shot past a tree is pending.

## 2026-10-11 — retreat off the hunt map returns through world nav

Consent: user asked to fix it now. World nav owns the return to the last farm or dungeon.

Intent: after mother tree, teleport, or a scroll, do not walk the saved patrol cell on the map just landed on.

Shared functions: `finish_retreat`. A walk saved during `traveling` still resumes when the character is still on the hunt map. Shop resume and `post_respawn` are unchanged.

Affected modes: retreat finish, then world nav (`post_retreat`). Same-map patrol resume stays a local walk.

Live result: pending an in-game test.

## 2026-10-11 — local clicks around alive bodies

Consent: implement the discussed subplan. A* remains the guide. A 15×15 BFS replaces the next click when a nearby living body blocks the straight walk.

Intent: travel, search, and loot hops stop walking into players, NPCs, and monsters that are near the bot.

Shared functions: `collect_body_tiles`, `plan_avoidance_click`, `click_clear`, `apply_avoidance`. Called from `emit_travel_hop`, `emit_search_hop`, and the loot approach. Body tiles are refreshed once per `decide()`.

Unchanged: global A*, combat clicks, `try_movement_unstick`. A window with no safe click still falls through to that sweep.

Affected modes: travel, search, loot, and any mode that walks through those hops (retreat, shop walk, world-nav walk).

Live result: removed from the bot on 2026-10-12. The walk was failing hops with ``avoid_blocked``.

## 2026-10-12 — avoidance walk removed from the bot

Consent: remove the tested avoidance walk from the main project. Integrate a plan only after the experiment shows it performs.

Intent: travel, search, and loot click the guide waypoint again. A nearby living body no longer replaces that click, aborts the hop, or fails the hop.

Shared functions no longer called by the bot: `collect_body_tiles`, `plan_avoidance_click`, `click_clear`, `apply_avoidance`. `decide()` no longer refreshes body tiles. `avoidance.py` stays for the avoid-view tool.

Unchanged: global A*, combat clicks, `try_movement_unstick`, the 2-second reclick, the 1-tile hop arrival.

Affected modes: travel, search, loot, and any mode that walks through those hops.

Live result: code removed. In-game walk after restart is pending.

## 2026-10-21 — schedule Start keeps the schedule character and routine

Consent: user asked to fix it on `impl/party-leader-logic` without touching single-bot logic and keeping party logic as is.

Intent: on Start, `_overlay_party_from_editor` re-applied the Party tab through a bare `ScheduleTask`. Its default `character="mage"` and empty routine overwrote the schedule just applied by `apply_task`. The schedule (elf, area_6 60 min) then ran as mage with `routine (0 entries)`, and the trial file was saved that way.

Change: only `UI/ui_qt/shell/schedule_shell.py` `_overlay_party_from_editor`. It applies the Party tab to a copy of the profile and copies back `party_*` fields only. `apply_runtime_settings` and the `ScheduleTask` defaults are unchanged.

Affected modes: main-window Start and scheduled login Start. Single-bot decision, movement, combat and HP code are unchanged. Party values are the same as before, checked for party off, leader on and member on.

Live result: pending. The next Start log should read `character=elf` and the routine should have 1 entry.

## 2026-10-21 — party wait log only when party is on

Consent: user asked to stop the `Party wait` log while party is off.

Change: `_log_party_until_farm` in `Engine/session/bot_controller.py` returns early when `profile.party_enabled` is false. The function is log only. Decisions, movement and the party socket are unchanged. With party on, the log is the same as before.

## 2026-10-22 — party invite accept from the in-game popup

Consent: user asked to read the invite dialog like `uidialogmon_930.c`, press Y when the text is a party invite, send an ack to the leader over the socket, drop the leader's invite notice and the member's 30 s wait, use the dist registry keys, and hold the IME in English for Y. User accepted that both PCs must run the same version (socket format changes).

Intent: the member accepts on what it sees on screen, not on a socket notice, and the leader counts the member joined once Y closed the popup.

Change:
- `uidialog_listen.c` (DLL rebuilt) lists open Yes/No confirms (`HudChatLayoutPCImpl` chat confirm panel + popup classes) under `confirm` with the text; registry keys `CHATCONFIRM_*` / `UICONFIRM_CLASSES` / `POPUP_VIS_OFF` copied from the dist registry. Popups are not added as `UIDLG_WIN_*`, so the Esc window gate does not close them.
- Member: `_06_party/invite_popup.py` matches the Korean invite text (파티 + 초대합니다 + 승낙; any 거래 text is never an invite) and the inviter name. `accept.InviteAccepter` rewritten: Y at once, again after 2 s if the popup is still open (max 3), accepted = popup closed after Y, then `invite_accept` to the leader (3 sends, one `accept_id`). A popup from someone other than the policy `leader_name` is left alone. Phase `left` once party memory showed the join and lost it for 10 s.
- Y: `GameChat.press_key(english=True)` clears 한글 mode on the game's default IME window (`WM_IME_CONTROL`) for the key and restores it after.
- Socket: `party_invite` / `publish_invite` / `take_invite` removed; new `invite_accept` frame (member → leader); policy carries `leader_name`.
- Leader: no notice and no `InviteGate`. `InviteHold` holds a new `/초대` while the member reports the popup open (max 30 s). Joined = leader party memory, or `sync.reported_joined` (member accepted the popup, or its own party memory). The 20 s `/초대` retry and the start wait are unchanged.

Affected modes: party member invite accept, leader invite/joined bookkeeping and the party monitor. Single-bot logic and the rally, follow, combat and HP code are unchanged.

Side effects to watch: a popup closed by its own timeout right after Y counts as accepted; a member restarted after an accept is not joined until it accepts or its memory shows the party. When the leader name cannot be read at setup, the member accepts any invite popup.

Live result: popup reading verified on a trade popup (ask 252). Invite accept and IME switch pending a live run on both PCs.