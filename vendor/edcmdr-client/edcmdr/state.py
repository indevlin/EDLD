"""Per-commander state built from journal events, emitted as protocol categories."""
import json
import re
import time
from datetime import datetime

from . import paths
from .config import SPEC

SHIP_NAMES: dict[str, str] = json.loads((paths.data_dir() / 'ships.json').read_text())
STAT_SECTIONS = set(SPEC['statistics_sections'])
RANK_KEYS = SPEC['rank_keys']
REP_KEYS = SPEC['reputation_keys']
DEFAULT_RANKS = SPEC['squadron_default_ranks']
CARRIER_TYPES = set(SPEC['carrier_types'])
MAX_SHIP_ID = 1_000_000
DEFAULT_RANK_RE = re.compile(r'^\$Squadron_DefaultRankName_Rank(\d+);?$', re.I)

EVENTS = frozenset({
    'Commander', 'NewCommander', 'LoadGame', 'Shutdown', 'Rank', 'Progress', 'Promotion', 'Reputation',
    'Statistics', 'SquadronStartup', 'JoinedSquadron', 'LeftSquadron', 'KickedFromSquadron',
    'DisbandedSquadron', 'SquadronPromotion', 'SquadronDemotion', 'Powerplay', 'PowerplayJoin',
    'PowerplayLeave', 'PowerplayDefect', 'PowerplayRank', 'PowerplayMerits', 'EngineerProgress',
    'Location', 'FSDJump', 'CarrierJump', 'Docked', 'Undocked', 'SupercruiseEntry', 'ApproachBody', 'LeaveBody',
    'StoredShips', 'Loadout', 'ShipyardSwap', 'ShipyardNew', 'ShipyardSell', 'ShipyardTransfer',
    'SetUserShipName', 'SellShipOnRebuy', 'ShipyardBuy', 'CarrierStats', 'CarrierLocation', 'Music',
    'CarrierBuy', 'CarrierFinance', 'CarrierBankTransfer', 'CarrierDepositFuel', 'CarrierCrewServices',
    'CarrierDockingPermission', 'CarrierNameChange', 'CarrierDecommission', 'CarrierCancelDecommission',
})


def rank_title(rank, name):
    """A squadron rank's title; the game's placeholder or no name means the default title for the rank."""
    m = DEFAULT_RANK_RE.match(name.strip()) if isinstance(name, str) else None
    if m:
        i = int(m.group(1))
        return DEFAULT_RANKS[i] if i < len(DEFAULT_RANKS) else None
    if isinstance(name, str) and name.strip() and not name.strip().startswith('$'):
        return name
    return DEFAULT_RANKS[rank] if isinstance(rank, int) and 0 <= rank < len(DEFAULT_RANKS) else None


def _ts(ev) -> int | None:
    try:
        return int(datetime.fromisoformat(ev['timestamp'].replace('Z', '+00:00')).timestamp())
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def ship_name(t: str) -> str:
    t = (t or '').lower()
    return SHIP_NAMES.get(t) or t.replace('_', ' ').title()


def is_ship(t: str, sid) -> bool:
    return isinstance(sid, int) and 0 <= sid < MAX_SHIP_ID and bool(t) and not t.lower().endswith('_taxi')


class Commander:
    def __init__(self, fid: str):
        self.fid = fid
        self.name = ''
        self.mode = 'Unknown'
        self.in_game = False
        self.last_event = 0.0
        self.ranks = {'rank': {}, 'progress': {}, 'reputation': {}}
        self.statistics: dict = {}
        self.squadron: dict | None = None
        self.powerplay: dict | None = None
        self.engineers: dict[int, dict] = {}
        self.location = {'system': None, 'body': None, 'station': None, 'docked': False}
        self.ships: dict[int, dict] = {}
        self.current: int | None = None
        self.loaded = False
        self.market: int | None = None
        self.markets: dict[int, dict] = {}
        self.carrier: int | None = None
        self.carriers: dict[int, dict] = {}

    # ── events ──────────────────────────────────────────────────────────────
    def handle(self, ev: dict) -> None:
        h = getattr(self, '_e_' + ev['event'], None)
        if h:
            h(ev)
        try:
            self.last_event = max(self.last_event, datetime.fromisoformat(ev['timestamp'].replace('Z', '+00:00')).timestamp())
        except (KeyError, TypeError, ValueError):
            pass

    def _e_Commander(self, ev):
        self.name = ev.get('Name') or self.name

    _e_NewCommander = _e_Commander

    def _e_LoadGame(self, ev):
        self.name = ev.get('Commander') or self.name
        mode = ev.get('GameMode')
        self.mode = mode if mode in ('Open', 'Solo', 'Group') else 'Unknown'
        self.in_game = True
        sid, t = ev.get('ShipID'), ev.get('Ship', '')
        if is_ship(t, sid):
            s = self._ship(sid, t)
            s['name'] = ev.get('ShipName') or s['name']
            s['ident'] = ev.get('ShipIdent') or s['ident']
            self.current = sid

    def _e_Shutdown(self, ev):
        self.in_game = False

    def _e_Music(self, ev):
        if ev.get('MusicTrack') == 'MainMenu':
            self.in_game = False

    def _e_Rank(self, ev):
        self.ranks['rank'].update({k: ev[k] for k in RANK_KEYS if isinstance(ev.get(k), int)})

    def _e_Progress(self, ev):
        self.ranks['progress'].update({k: ev[k] for k in RANK_KEYS if isinstance(ev.get(k), int)})

    def _e_Promotion(self, ev):
        for k in RANK_KEYS:
            if isinstance(ev.get(k), int):
                self.ranks['rank'][k] = ev[k]
                self.ranks['progress'][k] = 0

    def _e_Reputation(self, ev):
        self.ranks['reputation'].update({k: round(float(ev[k]), 2) for k in REP_KEYS
                                         if isinstance(ev.get(k), (int, float))})

    def _e_Statistics(self, ev):
        self.statistics = {k: {kk: vv for kk, vv in v.items() if isinstance(vv, (int, float)) and vv >= 0}
                           for k, v in ev.items() if k in STAT_SECTIONS and isinstance(v, dict)}

    def _e_SquadronStartup(self, ev):
        self.squadron = {'id': ev.get('SquadronID'), 'name': ev.get('SquadronName'), 'rank': ev.get('CurrentRank'),
                         'rank_name': rank_title(ev.get('CurrentRank'), ev.get('CurrentRankName'))}
        self._squadron_seen(ev)

    def _e_JoinedSquadron(self, ev):
        self.squadron = {'id': ev.get('SquadronID'), 'name': ev.get('SquadronName'), 'rank': None, 'rank_name': None}
        self._squadron_seen(ev)

    def _squadron_seen(self, ev):
        """When the journal gave the squadron's name, so the server keeps the newest one after a rename."""
        try:
            self.squadron['seen'] = int(datetime.fromisoformat(ev['timestamp'].replace('Z', '+00:00')).timestamp())
        except (KeyError, TypeError, ValueError, AttributeError):
            pass

    def _e_LeftSquadron(self, ev):
        self.squadron = None
        for cid in [k for k, c in self.carriers.items() if c['type'] == 'SquadronCarrier']:
            del self.carriers[cid]

    _e_KickedFromSquadron = _e_LeftSquadron
    _e_DisbandedSquadron = _e_LeftSquadron

    def _e_SquadronPromotion(self, ev):
        if self.squadron is not None:
            self.squadron['rank'] = ev.get('NewRank', self.squadron['rank'])
            # The journal names the new rank only sometimes.
            self.squadron['rank_name'] = rank_title(self.squadron['rank'], ev.get('NewRankName'))

    _e_SquadronDemotion = _e_SquadronPromotion

    def _e_Powerplay(self, ev):
        self.powerplay = {'power': ev.get('Power'), 'rank': ev.get('Rank'), 'merits': ev.get('Merits'),
                          'pledged': ev.get('TimePledged') if isinstance(ev.get('TimePledged'), int) else None}

    def _e_PowerplayJoin(self, ev):
        self.powerplay = {'power': ev.get('Power'), 'rank': 1, 'merits': 0, 'pledged': 0}

    def _e_PowerplayDefect(self, ev):
        self.powerplay = {'power': ev.get('ToPower'), 'rank': 1, 'merits': 0, 'pledged': 0}

    def _e_PowerplayLeave(self, ev):
        self.powerplay = None

    def _e_PowerplayRank(self, ev):
        if self.powerplay is not None and isinstance(ev.get('Rank'), int):
            self.powerplay['rank'] = ev['Rank']

    def _e_PowerplayMerits(self, ev):
        if self.powerplay is not None and isinstance(ev.get('TotalMerits'), int):
            self.powerplay['merits'] = ev['TotalMerits']

    def _e_EngineerProgress(self, ev):
        items = ev.get('Engineers') if isinstance(ev.get('Engineers'), list) else [ev]
        for e in items:
            if isinstance(e, dict) and isinstance(e.get('EngineerID'), int) and e.get('Engineer'):
                prev = self.engineers.get(e['EngineerID'], {})
                self.engineers[e['EngineerID']] = {
                    'name': e['Engineer'], 'id': e['EngineerID'],
                    'state': e.get('Progress') or prev.get('state'),
                    'rank': e.get('Rank', prev.get('rank')),
                }

    def _seen(self, mid, name=None, system=None) -> None:
        """What a market (station or carrier) is called and where it was last seen."""
        if not isinstance(mid, int):
            return
        m = self.markets.setdefault(mid, {'name': None, 'system': None})
        if name and not ((mid == self.carrier or mid in self.carriers) and m['name']):
            m['name'] = name
        if system:
            m['system'] = system

    def _e_Location(self, ev):
        docked = bool(ev.get('Docked'))
        self.location = {'system': ev.get('StarSystem'), 'body': ev.get('Body'),
                         'station': ev.get('StationName') if docked else None, 'docked': docked}
        self.market = ev.get('MarketID') if docked else None
        if docked:
            self._seen(ev.get('MarketID'), ev.get('StationName'), ev.get('StarSystem'))

    def _e_CarrierJump(self, ev):
        self._e_Location(ev)
        k = self.carriers.get(ev.get('MarketID'))
        if k is not None and ev.get('StarSystem'):
            k.update(system=ev['StarSystem'], seen=_ts(ev) or k['seen'])

    def _e_CarrierLocation(self, ev):
        self._seen(ev.get('CarrierID'), system=ev.get('StarSystem'))
        k = self.carriers.get(ev.get('CarrierID'))
        if k is not None and ev.get('StarSystem'):
            k['system'] = ev['StarSystem']

    # ── carriers: the commander's own fleet carrier and the squadron carrier they can open ──
    def _carrier(self, ev, create: bool = False, touch: bool = True) -> dict | None:
        cid = ev.get('CarrierID')
        if not isinstance(cid, int) or cid <= 0:
            return None
        k = self.carriers.get(cid)
        if k is None and create:
            t = ev.get('CarrierType') or 'FleetCarrier'
            if t not in CARRIER_TYPES:
                return None
            if t == 'FleetCarrier':
                for old in [i for i, c in self.carriers.items() if c['type'] == 'FleetCarrier']:
                    del self.carriers[old]
            k = self.carriers[cid] = {'id': cid, 'type': t, 'callsign': None, 'name': None, 'system': None,
                                      'docking': None, 'notorious': False, 'fuel': None, 'space': None, 'services': [],
                                      'ship_packs': None, 'module_packs': None, 'balance': None, 'reserve': None,
                                      'decommission': None, 'seen': None}
        if k is not None and touch:
            k['seen'] = _ts(ev) or k['seen']
        return k

    def _carrier_name(self, k: dict) -> None:
        if k['name'] and k['callsign']:
            self.markets.setdefault(k['id'], {'name': None, 'system': None})['name'] = f"{k['name']} ({k['callsign']})"

    def _e_CarrierStats(self, ev):
        if ev.get('CarrierType', 'FleetCarrier') == 'FleetCarrier' and isinstance(ev.get('CarrierID'), int):
            self.carrier = ev['CarrierID']
        k = self._carrier(ev, create=True)
        if k is None:
            return
        fin = ev.get('Finance') if isinstance(ev.get('Finance'), dict) else {}
        sp = ev.get('SpaceUsage') if isinstance(ev.get('SpaceUsage'), dict) else {}
        crew = ev.get('Crew') if isinstance(ev.get('Crew'), list) else []
        k.update(callsign=ev.get('Callsign') or k['callsign'], name=ev.get('Name') or k['name'],
                 docking=ev.get('DockingAccess', k['docking']), notorious=bool(ev.get('AllowNotorious')),
                 fuel=ev.get('FuelLevel', k['fuel']),
                 space={'total': sp.get('TotalCapacity'), 'crew': sp.get('Crew'), 'cargo': sp.get('Cargo'),
                        'free': sp.get('FreeSpace')} if sp else k['space'],
                 services=[c['CrewRole'] for c in crew if isinstance(c, dict) and c.get('CrewRole')
                           and c.get('Activated') and c.get('Enabled', True) and c['CrewRole'] != 'Captain'],
                 ship_packs=len(ev['ShipPacks']) if isinstance(ev.get('ShipPacks'), list) else k['ship_packs'],
                 module_packs=len(ev['ModulePacks']) if isinstance(ev.get('ModulePacks'), list) else k['module_packs'],
                 balance=fin.get('CarrierBalance', k['balance']), reserve=fin.get('ReserveBalance', k['reserve']))
        if not ev.get('PendingDecommission'):
            k['decommission'] = None
        self._carrier_name(k)

    def _e_CarrierBuy(self, ev):
        k = self._carrier(ev, create=True)
        if k is not None:
            k['system'] = ev.get('Location') or k['system']

    def _e_CarrierFinance(self, ev):
        k = self._carrier(ev)
        if k is not None:
            k.update(balance=ev.get('CarrierBalance', k['balance']), reserve=ev.get('ReserveBalance', k['reserve']))

    def _e_CarrierBankTransfer(self, ev):
        k = self._carrier(ev)
        if k is not None:
            k['balance'] = ev.get('CarrierBalance', k['balance'])

    def _e_CarrierDepositFuel(self, ev):
        k = self._carrier(ev)
        if k is not None:
            k['fuel'] = ev.get('Total', k['fuel'])

    def _e_CarrierCrewServices(self, ev):
        role, op = ev.get('CrewRole'), ev.get('Operation')
        k = self._carrier(ev, touch=op != 'Replace')
        if k is None or not role or role == 'Captain':
            return
        if op in ('Activate', 'Resume') and role not in k['services']:
            k['services'] = k['services'] + [role]
        elif op in ('Deactivate', 'Pause'):
            k['services'] = [r for r in k['services'] if r != role]

    def _e_CarrierDockingPermission(self, ev):
        k = self._carrier(ev)
        if k is not None:
            k.update(docking=ev.get('DockingAccess', k['docking']), notorious=bool(ev.get('AllowNotorious', k['notorious'])))

    def _e_CarrierNameChange(self, ev):
        k = self._carrier(ev)
        if k is not None:
            k.update(name=ev.get('Name') or k['name'], callsign=ev.get('Callsign') or k['callsign'])
            self._carrier_name(k)

    def _e_CarrierDecommission(self, ev):
        k = self._carrier(ev)
        if k is not None and isinstance(ev.get('ScrapTime'), int):
            k['decommission'] = ev['ScrapTime']

    def _e_CarrierCancelDecommission(self, ev):
        k = self._carrier(ev)
        if k is not None:
            k['decommission'] = None

    def carriers_out(self, now: float | None = None) -> list[dict]:
        """Carriers still in service, own fleet carrier first."""
        now = time.time() if now is None else now
        live = [k for k in self.carriers.values() if not (k['decommission'] and k['decommission'] <= now)]
        return [dict(k) for k in sorted(live, key=lambda k: (k['type'] != 'FleetCarrier', k['id']))]

    def _e_FSDJump(self, ev):
        self.location = {'system': ev.get('StarSystem'), 'body': None, 'station': None, 'docked': False}
        self.market = None

    def _e_Docked(self, ev):
        self.location.update(station=ev.get('StationName'), docked=True, system=ev.get('StarSystem') or self.location['system'])
        self.market = ev.get('MarketID')
        self._seen(ev.get('MarketID'), ev.get('StationName'), self.location['system'])

    def _e_Undocked(self, ev):
        self.location.update(station=None, docked=False)
        self.market = None

    def _e_SupercruiseEntry(self, ev):
        self.location.update(body=None, station=None, docked=False)

    def _e_ApproachBody(self, ev):
        self.location['body'] = ev.get('Body')

    def _e_LeaveBody(self, ev):
        self.location['body'] = None

    def _ship(self, sid: int, t: str) -> dict:
        s = self.ships.setdefault(sid, {'id': sid, 'type': t.lower(), 'type_name': ship_name(t), 'name': None,
                                        'ident': None, 'value': None, 'hull': None, 'rebuy': None, 'jump': None,
                                        'cargo': None, 'system': None, 'market': None, 'modules': [],
                                        'loadout': False})
        s['type'] = t.lower()
        s['type_name'] = ship_name(t)
        return s

    def _e_StoredShips(self, ev):
        seen = set()
        for s in ev.get('ShipsHere') or []:
            if is_ship(s.get('ShipType', ''), s.get('ShipID')):
                x = self._ship(s['ShipID'], s['ShipType'])
                x.update(name=s.get('Name') or x['name'], system=ev.get('StarSystem'), market=ev.get('MarketID'))
                if not x['loadout']:
                    x['value'] = s.get('Value', x['value'])
                seen.add(s['ShipID'])
        self._seen(ev.get('MarketID'), ev.get('StationName'), ev.get('StarSystem'))
        for s in ev.get('ShipsRemote') or []:
            if is_ship(s.get('ShipType', ''), s.get('ShipID')):
                x = self._ship(s['ShipID'], s['ShipType'])
                transit = bool(s.get('InTransit'))
                x.update(name=s.get('Name') or x['name'], system=None if transit else s.get('StarSystem'),
                         market=None if transit else s.get('ShipMarketID'))
                if not x['loadout']:
                    x['value'] = s.get('Value') or x['value']
                seen.add(s['ShipID'])
        for sid in list(self.ships):
            if sid not in seen and sid != self.current:
                del self.ships[sid]

    def _e_Loadout(self, ev):
        sid, t = ev.get('ShipID'), ev.get('Ship', '')
        if not is_ship(t, sid):
            return
        s = self._ship(sid, t)
        mods = []
        for m in ev.get('Modules') or []:
            if not isinstance(m, dict) or not m.get('Slot') or not m.get('Item'):
                continue
            e = m.get('Engineering')
            eng = None
            if isinstance(e, dict):
                eng = {'blueprint': e.get('BlueprintName'), 'level': e.get('Level'), 'quality': e.get('Quality'),
                       'experimental': e.get('ExperimentalEffect_Localised')}
            mods.append({'slot': m['Slot'], 'item': m['Item'], 'eng': eng})
        hv, mv = ev.get('HullValue'), ev.get('ModulesValue')
        s.update(name=ev.get('ShipName') or s['name'], ident=ev.get('ShipIdent') or s['ident'],
                 value=(hv or 0) + (mv or 0) if (hv or mv) else s['value'], hull=ev.get('HullHealth'), loadout=True,
                 rebuy=ev.get('Rebuy'), jump=ev.get('MaxJumpRange'), cargo=ev.get('CargoCapacity'), modules=mods)
        self.current = sid

    def _store_here(self, sid) -> None:
        if sid in self.ships:
            self.ships[sid].update(system=self.location['system'], market=self.market)

    def _e_ShipyardBuy(self, ev):
        self._store_here(ev.get('StoreShipID'))
        self.ships.pop(ev.get('SellShipID'), None)

    def _e_ShipyardSwap(self, ev):
        self._store_here(ev.get('StoreShipID'))
        self.ships.pop(ev.get('SellShipID'), None)
        sid, t = ev.get('ShipID'), ev.get('ShipType', '')
        if is_ship(t, sid):
            self._ship(sid, t)
            self.current = sid

    def _e_ShipyardNew(self, ev):
        sid, t = ev.get('NewShipID'), ev.get('ShipType', '')
        if is_ship(t, sid):
            self._ship(sid, t)
            self.current = sid

    def _e_ShipyardSell(self, ev):
        self.ships.pop(ev.get('SellShipID'), None)

    _e_SellShipOnRebuy = _e_ShipyardSell

    def _e_ShipyardTransfer(self, ev):
        if ev.get('ShipID') in self.ships:
            self.ships[ev['ShipID']].update(system=self.location['system'], market=ev.get('MarketID') or self.market)

    def _e_SetUserShipName(self, ev):
        sid, t = ev.get('ShipID'), ev.get('Ship', '')
        if is_ship(t, sid):
            s = self._ship(sid, t)
            s.update(name=ev.get('UserShipName') or s['name'], ident=ev.get('UserShipIdent') or s['ident'])

    # ── output ──────────────────────────────────────────────────────────────
    def categories(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        if self.name:
            out['identity'] = {'name': self.name}
        if self.ranks['rank']:
            out['ranks'] = self.ranks
        if self.statistics:
            out['statistics'] = self.statistics
        if self.squadron is not None or self.loaded:
            out['squadron'] = self.squadron or {'id': None, 'name': None, 'rank': None, 'rank_name': None}
        if self.powerplay is not None:
            out['powerplay'] = self.powerplay
        carriers = self.carriers_out()
        if carriers:
            out['carriers'] = {'carriers': carriers}
        if self.engineers:
            out['engineering'] = {'engineers': sorted(self.engineers.values(), key=lambda e: e['name'])}
        ships = sorted(self.ships.values(), key=lambda s: s['id'])
        if self.location['system']:
            out['location'] = dict(self.location, ships=[w for s in ships if s['id'] != self.current
                                                         and (w := self._where(s))['system']])
        if ships:
            out['fleet'] = {'current': self.current if self.current in self.ships else None,
                            'ships': [{k: v for k, v in s.items() if k not in ('system', 'market', 'loadout')}
                                      for s in ships]}
        return out

    def _where(self, s: dict) -> dict:
        """A stored ship's place; one on a fleet carrier is where the carrier was last seen."""
        m = self.markets.get(s['market']) if s['market'] is not None else None
        return {'id': s['id'], 'system': (m or {}).get('system') or s['system'], 'station': (m or {}).get('name')}

    def presence(self, running: bool) -> dict:
        """In game: the game is running and a session is loaded (LoadGame, with no Shutdown or main menu since)."""
        live = self.in_game and running
        cur = self.ships.get(self.current)
        return {'in_game': live, 'mode': self.mode if live else 'Unknown',
                'ship': cur['type_name'] if live and cur else None}
