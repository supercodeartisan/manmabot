"""check_configs.py - verify 11-11analysis overlays against registry v37.

Each overlay file keeps its original value format (some use 0x, some plain hex),
so checks are done on the exact expected line text plus JSON value equality.
"""
import io
import json
import os
import re
import sys

B = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(B, 'registry', 'LC930_REGISTRY.txt')

reg = {}
for ln in io.open(REG, encoding='utf-8'):
    m = re.match(r'^([A-Za-z0-9_]+)=(0x[0-9A-Fa-f]+)\s*$', ln)
    if m:
        reg[m.group(1)] = int(m.group(2), 16)

fail = 0


def need(path, lines):
    global fail
    t = io.open(os.path.join(B, path), encoding='utf-8', errors='replace').read()
    bad = [l for l in lines if l not in t]
    print('%-34s %s' % (path, 'OK' if not bad else 'MISSING ' + str(bad)))
    if bad:
        fail += 1


def hx(k):
    return '0x%X' % reg[k]


sb = reg['ST_BLOCK']
need(r'registry\char_offsets.txt', [
    'MGR=' + hx('MGR'), 'CD_VFT=' + hx('CD_VFT'),
    'CD_OFF=' + hx('CD_OFF'), 'VFT_STATUS=' + hx('VFT_STATUS')])
need(r'registry\entity_offsets.txt', [
    'MGR=' + hx('MGR'),
    'ACTOR_VFT=' + hx('VFT_ACTORSUBS'),
    'VFT_PRES_A=' + hx('VFT_PRES_A'),
    'VFT_PRES_B=' + hx('VFT_PRES_B'),
    'ACT_VFT=%X' % reg['VFT_AC'],
    'ATTACK_ACT_VFT=%X' % reg['VFT_ATTACKACT'],
    'DEATH_VFT=%X' % reg['VFT_DEATH'],
    'DEADBODY_VFT=%X' % reg['VFT_DEADBODY'],
    'PLAYER_X=%X' % reg['PLAYER_X'],
    'PLAYER_Y=%X' % reg['PLAYER_Y'],
    'PLAYER_HP=%X' % (sb + reg['ST_HP']),
    'PLAYER_MAXHP=%X' % (sb + reg['ST_MAXHP']),
    'PLAYER_MP=%X' % (sb + reg['ST_MP']),
    'PLAYER_MAXMP=%X' % (sb + reg['ST_MAXMP']),
    'PLAYER_LEVEL=%X' % (sb + reg['ST_LEVEL']),
    'CAM_GLOB=%X' % reg['CAM_GLOB'],
    'VFT_SELF=%X' % reg['VFT_SELF'],
    'VFT_PLAYER=%X' % reg['VFT_PLAYER'],
    'VFT_INTERACTIVE=%X' % reg['VFT_NPC'],
])
need(r'registry\inventory_offsets.txt', [
    'MGR=' + hx('MGR'), 'INV_VFT=' + hx('VFT_INVENTORY'),
    'ITEM_VFT=' + hx('ITEM_VFT'), 'MSG_ANCHOR_RVA=' + hx('MSG_ANCHOR_RVA'),
    'INV_SUB_IDX=26'])
need(r'registry\skill_offsets.txt', [
    'MGR=' + hx('MGR'), 'HSD_VFT2=%X' % reg['VFT_HUDSLOT'], 'HSD_IDX=30'])

# JSON overlays
j = json.load(io.open(os.path.join(B, 'registry', 'offsets.json'), encoding='utf-8-sig'))
for key, val in (('PosXAbs', reg['PLAYER_X']), ('PosYAbs', reg['PLAYER_Y']),
                 ('ExperiencePct64', reg['ExperiencePct64'])):
    ok = j.get(key) == val
    print('%-34s %s' % ('offsets.json:' + key, 'OK' if ok else 'MISMATCH %r != %r' % (j.get(key), val)))
    fail += 0 if ok else 1
ok = j.get('MapSubsystemVftRva', '').lower() == hx('VFT_MAPSUBS').lower()
print('%-34s %s' % ('offsets.json:MapSubsystemVftRva', 'OK' if ok else 'MISMATCH'))
fail += 0 if ok else 1

for f in ('settings_print_state.json', 'settings_attacks_me.json', 'settings_contested_mobs.json'):
    d = json.load(io.open(os.path.join(B, 'registry', f), encoding='utf-8-sig'))
    pairs = {'ent_mgr_offset': hx('MGR'), 'grid_vft': hx('VFT_ACTORSUBS')}
    if f == 'settings_print_state.json':
        pairs.update({'player_x_offset': hx('PLAYER_X'), 'player_y_offset': hx('PLAYER_Y'),
                      'player_hp_offset': '0x%X' % (sb + reg['ST_HP']),
                      'player_level_offset': '0x%X' % (sb + reg['ST_LEVEL']),
                      'vft_pres_a': hx('VFT_PRES_A'), 'vft_pres_b': hx('VFT_PRES_B')})
    else:
        pairs.update({'act_vft': hx('VFT_AC'), 'attack_act_vft': hx('VFT_ATTACKACT'),
                      'vft_self': hx('VFT_SELF'), 'vft_player': hx('VFT_PLAYER'),
                      'vft_monster': hx('VFT_MONSTER'), 'vft_summon': hx('VFT_SUMMON')})
    bad = [(k, d.get(k), v) for k, v in pairs.items() if str(d.get(k)).lower() != v.lower()]
    print('%-34s %s' % ('registry\\' + f, 'OK' if not bad else 'MISMATCH ' + str(bad)))
    fail += 0 if not bad else 1

print()
print('== check_configs: %s ==' % ('PASS' if fail == 0 else 'FAIL'))
sys.exit(0 if fail == 0 else 1)
