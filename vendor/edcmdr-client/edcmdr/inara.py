"""Inara API events from journal events, one commander each."""
import os

URL = 'https://inara.cz/inapi/v1/'

# The application key Inara issues for EDCMDR-client; builds get it from the INARA_APP_KEY secret.
# Empty until Inara issues it: uploads then use the player's own Inara API key only.
try:
    from ._build_secret import INARA_APP_KEY  # type: ignore[attr-defined]
except ImportError:
    INARA_APP_KEY = os.environ.get('INARA_APP_KEY', '').strip()

RANKS = {'Combat': 'combat', 'Trade': 'trade', 'Explore': 'explore', 'Soldier': 'soldier',
         'Exobiologist': 'exobiologist', 'CQC': 'cqc', 'Federation': 'federation', 'Empire': 'empire'}


def throttled(status, text: str) -> bool:
    """Inara's "slow down": access revoked for an hour (status 400 with that text, or 429)."""
    t = (text or '').lower()
    return status == 429 or (status == 400 and ('too much requests' in t or 'temporarily revoked' in t))


class Builder:
    """Tracks what Inara wants alongside events and turns events into Inara events."""

    def __init__(self):
        self.rank: dict[str, int] = {}
        self.progress: dict[str, float] = {}
        self.credits = self.wealth = None
        self.ship_type = self.ship_id = None
        self.pos = None
        self.power = self.pp_rank = self.pp_merits = None
        self.last_loadout = None

    def _figures(self, ev: dict) -> None:
        """Ranks, progress, credits and wealth: kept from history too, so live events can carry them."""
        e = ev.get('event')
        if e == 'Rank':
            self.rank.update({RANKS[k]: int(ev[k]) for k in RANKS if isinstance(ev.get(k), int)})
        elif e == 'Progress':
            self.progress.update({RANKS[k]: ev[k] / 100.0 for k in RANKS if isinstance(ev.get(k), (int, float))})
        elif e == 'Promotion':
            for k in RANKS:
                if isinstance(ev.get(k), int):
                    self.rank[RANKS[k]], self.progress[RANKS[k]] = ev[k], 0.0
        elif e == 'LoadGame' and isinstance(ev.get('Credits'), int) and ev['Credits'] >= 0:
            self.credits = ev['Credits']
        elif e == 'Statistics':
            w = (ev.get('Bank_Account') or {}).get('Current_Wealth')
            if isinstance(w, int) and w >= 0:
                self.wealth = w

    def track(self, ev: dict) -> None:
        self._figures(ev)
        e = ev.get('event')
        if e in ('LoadGame', 'Loadout'):
            self.ship_type = ev.get('Ship') or self.ship_type
            self.ship_id = ev.get('ShipID', self.ship_id)
        if e in ('FSDJump', 'CarrierJump', 'Location') and ev.get('StarPos'):
            self.pos = ev['StarPos']
        if e == 'Powerplay':
            self.power, self.pp_rank, self.pp_merits = ev.get('Power'), ev.get('Rank'), ev.get('Merits')
        elif e in ('PowerplayJoin', 'PowerplayDefect'):
            self.power, self.pp_rank, self.pp_merits = ev.get('Power') or ev.get('ToPower'), 1, 0
        elif e == 'PowerplayLeave':
            self.power = None
        elif e == 'PowerplayRank':
            self.pp_rank = ev.get('Rank', self.pp_rank)
        elif e == 'PowerplayMerits':
            self.pp_merits = ev.get('TotalMerits', self.pp_merits)
        if e in ('ShipyardBuy', 'ShipyardSwap'):
            self.last_loadout = None

    def _ranks(self) -> list[dict]:
        out = []
        for k, v in self.rank.items():
            r = {'rankName': k, 'rankValue': v}
            if k in self.progress:
                r['rankProgress'] = round(self.progress[k], 4)
            out.append(r)
        return out

    def _ship(self, d: dict) -> dict:
        if self.ship_type:
            d['shipType'] = self.ship_type
        if self.ship_id is not None:
            d['shipGameID'] = self.ship_id
        return d

    def events(self, ev: dict) -> list[tuple[str, dict | list]]:
        """(eventName, eventData) pairs for a live event. Call track(ev) afterwards."""
        e = ev.get('event', '')
        out: list = []
        self._figures(ev)
        if e == 'LoadGame':
            if isinstance(ev.get('Credits'), int) and ev['Credits'] >= 0:
                d = {'commanderCredits': self.credits}
                if self.wealth is not None:
                    d['commanderAssets'] = self.wealth
                out.append(('setCommanderCredits', d))
            if self.rank:
                out.append(('setCommanderRankPilot', self._ranks()))
        elif e == 'Promotion':
            out.append(('setCommanderRankPilot', self._ranks()))
        elif e == 'Statistics':
            if self.wealth is not None and self.credits is not None:
                out.append(('setCommanderCredits', {'commanderCredits': self.credits, 'commanderAssets': self.wealth}))
        elif e == 'Reputation':
            reps = [{'factionName': k, 'reputationValue': ev[k] / 100.0}
                    for k in ('Federation', 'Empire', 'Alliance', 'Independent') if isinstance(ev.get(k), (int, float))]
            if reps:
                out.append(('setCommanderReputationMajorFaction', reps))
        elif e == 'EngineerProgress':
            eng = []
            for x in ev.get('Engineers') or [ev]:
                if isinstance(x, dict) and x.get('Engineer') and x.get('Progress'):
                    d = {'engineerName': x['Engineer'], 'rankStage': x['Progress']}
                    if isinstance(x.get('Rank'), int):
                        d['rankValue'] = x['Rank']
                    eng.append(d)
            if eng:
                out.append(('setCommanderRankEngineer', eng))
        elif e in ('Powerplay', 'PowerplayJoin', 'PowerplayRank', 'PowerplayMerits'):
            power = ev.get('Power') or self.power
            rank = ev.get('Rank', 1 if e == 'PowerplayJoin' else self.pp_rank)
            merits = ev.get('Merits', ev.get('TotalMerits', self.pp_merits))
            if power:
                d = {'powerName': power}
                if rank is not None:
                    d['rankValue'] = int(rank)
                if merits is not None:
                    d['meritsValue'] = int(merits)
                out.append(('setCommanderRankPower', d))
        elif e == 'PowerplayLeave' and self.power:
            out.append(('setCommanderRankPower', {'powerName': self.power, 'rankValue': 0}))
        elif e in ('FSDJump', 'CarrierJump', 'Location') and ev.get('StarSystem'):
            d = {'starsystemName': ev['StarSystem']}
            if ev.get('StarPos') or self.pos:
                d['starsystemCoords'] = ev.get('StarPos') or self.pos
            if e == 'FSDJump' and isinstance(ev.get('JumpDist'), (int, float)):
                d['jumpDistance'] = round(float(ev['JumpDist']), 2)
            elif ev.get('Docked') or e == 'CarrierJump':
                if ev.get('StationName'):
                    d['stationName'] = ev['StationName']
                if isinstance(ev.get('MarketID'), int):
                    d['marketID'] = ev['MarketID']
            name = {'FSDJump': 'addCommanderTravelFSDJump', 'CarrierJump': 'addCommanderTravelCarrierJump',
                    'Location': 'setCommanderTravelLocation'}[e]
            out.append((name, self._ship(d)))
        elif e == 'Docked':
            d = {'starsystemName': ev.get('StarSystem', ''), 'stationName': ev.get('StationName', '')}
            if isinstance(ev.get('MarketID'), int):
                d['marketID'] = ev['MarketID']
            out.append(('addCommanderTravelDock', self._ship(d)))
        elif e == 'MissionAccepted' and isinstance(ev.get('MissionID'), int):
            d = {'missionGameID': ev['MissionID'], 'missionName': ev.get('Name', '')}
            if ev.get('Faction'):
                d['minorfactionName'] = ev['Faction']
            if ev.get('Expiry'):
                d['missionExpiry'] = ev['Expiry']
            out.append(('addCommanderMission', d))
        elif e == 'MissionCompleted' and isinstance(ev.get('MissionID'), int):
            out.append(('setCommanderMissionCompleted', {'missionGameID': ev['MissionID'],
                                                         'rewardCredits': int(ev.get('Reward') or 0)}))
        elif e in ('MissionFailed', 'MissionAbandoned') and isinstance(ev.get('MissionID'), int):
            out.append((f'setCommander{e}', {'missionGameID': ev['MissionID']}))
        elif e == 'Loadout' and ev.get('Ship'):
            out += self._loadout(ev)
        elif e == 'ShipyardSell' and ev.get('ShipType'):
            d = {'shipType': ev['ShipType']}
            if isinstance(ev.get('SellShipID'), int):
                d['shipGameID'] = ev['SellShipID']
            out.append(('setCommanderShipDestroyed', d))
        elif e == 'StoredShips':
            for here, key in ((True, 'ShipsHere'), (False, 'ShipsRemote')):
                for s in ev.get(key) or []:
                    if isinstance(s, dict) and s.get('ShipType'):
                        d = {'shipType': s['ShipType'], 'isCurrentShip': False, 'shipInGarage': not here}
                        if isinstance(s.get('ShipID'), int):
                            d['shipGameID'] = s['ShipID']
                        if s.get('Name'):
                            d['shipName'] = s['Name']
                        if not here:
                            if s.get('StarSystem'):
                                d['shipStarSystem'] = s['StarSystem']
                            if s.get('InTransit') is not None:
                                d['shipInTransit'] = bool(s['InTransit'])
                        out.append(('setCommanderShip', d))
        elif e == 'SetUserShipName' and ev.get('Ship'):
            d = {'shipType': ev['Ship'], 'isCurrentShip': True}
            if isinstance(ev.get('ShipID'), int):
                d['shipGameID'] = ev['ShipID']
            if ev.get('UserShipName'):
                d['shipName'] = ev['UserShipName']
            if ev.get('UserShipId'):
                d['shipIdent'] = ev['UserShipId']
            out.append(('setCommanderShip', d))
        elif e == 'Died':
            d = {}
            if ev.get('KillerShip'):
                d = {'killerShipType': ev['KillerShip'], 'isPlayerKill': ev.get('KillerRank') is not None}
            out.append(('addCommanderCombatDeath', d))
        elif e == 'Materials':
            mats = [{'itemName': m.get('Name', ''), 'itemCount': int(m.get('Count', 0)), 'itemCategory': cat}
                    for cat, key in (('raw', 'Raw'), ('manufactured', 'Manufactured'), ('encoded', 'Encoded'))
                    for m in ev.get(key) or [] if isinstance(m, dict)]
            if mats:
                out.append(('setCommanderInventoryMaterials', mats))
        if e == 'FSDJump' and self.rank:
            out.append(('setCommanderRankPilot', self._ranks()))
        return out

    def _loadout(self, ev: dict) -> list:
        out = []
        d = {'shipType': ev['Ship'], 'isCurrentShip': True}
        if isinstance(ev.get('ShipID'), int):
            d['shipGameID'] = ev['ShipID']
        for k, ik in (('ShipName', 'shipName'), ('ShipIdent', 'shipIdent')):
            if ev.get(k):
                d[ik] = ev[k]
        for k, ik in (('HullValue', 'shipHullValue'), ('ModulesValue', 'shipModulesValue'), ('Rebuy', 'shipRebuyCost'),
                      ('CargoCapacity', 'cargoCapacity')):
            if isinstance(ev.get(k), int):
                d[ik] = ev[k]
        if isinstance((ev.get('FuelCapacity') or {}).get('Main'), (int, float)):
            d['fuelCapacity'] = round(float(ev['FuelCapacity']['Main']), 2)
        if isinstance(ev.get('MaxJumpRange'), (int, float)):
            d['maxJumpRange'] = round(float(ev['MaxJumpRange']), 2)
        out.append(('setCommanderShip', d))
        mods = []
        for m in ev.get('Modules') or []:
            if not isinstance(m, dict) or not m.get('Slot') or not m.get('Item'):
                continue
            x = {'slotName': m['Slot'], 'itemName': m['Item'], 'isOn': bool(m.get('On', True)),
                 'itemPriority': int(m.get('Priority', 0)), 'itemHealth': round(float(m.get('Health', 1.0)), 4)}
            for k, ik in (('Value', 'itemValue'), ('AmmoInClip', 'itemAmmoClip'), ('AmmoInHopper', 'itemAmmoHopper')):
                if isinstance(m.get(k), int):
                    x[ik] = m[k]
            if m.get('Hot') is not None:
                x['isHot'] = bool(m['Hot'])
            eng = m.get('Engineering')
            if isinstance(eng, dict) and eng.get('BlueprintName'):
                bp = {'blueprintName': eng['BlueprintName'], 'blueprintLevel': int(eng.get('Level', 0)),
                      'blueprintQuality': round(float(eng.get('Quality', 0)), 2), 'modifiers': []}
                if eng.get('ExperimentalEffect'):
                    bp['experimentalEffect'] = eng['ExperimentalEffect']
                for mo in eng.get('Modifiers') or []:
                    if not isinstance(mo, dict):
                        continue
                    y = {'name': mo.get('Label', '')}
                    if 'OriginalValue' in mo:
                        y.update(value=mo.get('Value'), originalValue=mo['OriginalValue'], lessIsGood=int(mo.get('LessIsGood', 0)))
                    elif 'ValueStr' in mo:
                        y['value'] = mo['ValueStr']
                    elif 'Value' in mo:
                        y['value'] = mo['Value']
                    bp['modifiers'].append(y)
                x['engineering'] = bp
            mods.append(x)
        if mods:
            lo = {'shipType': ev['Ship'], 'shipLoadout': mods}
            if isinstance(ev.get('ShipID'), int):
                lo['shipGameID'] = ev['ShipID']
            if lo != self.last_loadout:
                self.last_loadout = lo
                out.append(('setCommanderShipLoadout', lo))
        return out
