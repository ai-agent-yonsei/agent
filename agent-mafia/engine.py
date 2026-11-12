"""에이전트 마피아 게임 엔진.

모든 접속자가 하나의 Game 객체를 공유한다(Streamlit 프로세스 하나 = 게임 하나).
라운드 진행은 진행자가 버튼을 누르면 서버의 백그라운드 스레드에서 돌아가므로,
진행자 브라우저를 닫아도 라운드는 끝까지 진행된다.
"""
import copy
import json
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

ROLE_KO = {"mafia": "마피아", "citizen": "시민"}
PHASE_KO = {
    "lobby": "참가 대기", "writing": "프롬프트 작성", "day": "낮 토론", "vote": "투표",
    "night": "밤", "strategy": "작전 타임", "ended": "게임 종료",
}
DEFAULT_SETTINGS = {"mafia": 2, "max_rounds": 5, "passes": 2, "strategy_sec": 60, "reflect": True}
EDITABLE_PHASES = ("lobby", "writing", "strategy")
STEP_KO = {"talking": "낮 토론", "await_vote": "투표 대기", "voting": "투표 중",
           "await_night": "밤 대기", "night": "밤", "reflecting": "작전 타임"}


def phase_name(s):
    return STEP_KO.get(s.get("step")) or PHASE_KO.get(s["status"], s["status"])

BOT_NAMES = ["하늘", "바다", "노을", "별빛", "새벽", "들꽃", "구름", "솔바람", "단풍", "은하",
             "파도", "이슬", "보름", "산들", "여울", "가람"]
BOT_PROMPTS = [
    "논리형 탐정. 다른 사람 발언끼리의 모순을 찾아 근거를 한 가지 들고 지목한다.",
    "조용한 관찰자. 짧게 말하고, 대체로 다수 의견을 따르되 이유는 꼭 하나 댄다.",
    "공격형. 매 라운드 가장 수상한 한 명을 정해 끝까지 몰아붙인다.",
    "중재형. 감정적인 비난을 진정시키고, 증거 없는 지목에는 반대한다.",
    "말투 분석가. 갑자기 말투나 입장이 바뀐 사람을 의심한다.",
    "신뢰 쌓기형. 먼저 다른 사람의 좋은 추리를 인정하며 동맹을 만든다.",
    "통계형. 투표 기록을 보고 늘 같은 쪽에 몰려 투표하는 두 사람을 의심한다.",
    "직설형. 자기 생각을 숨기지 않고 매번 분명하게 한 명을 지목한다.",
]
CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


# ---------------------------------------------------------------- helpers
def seat_by_id(s, pid):
    return next((x for x in s["seats"] if x["id"] == pid), None)


def seat_by_no(s, n):
    return next((x for x in s["seats"] if x["seat"] == n), None)


def alive(s):
    return [x for x in s["seats"] if x["alive"]]


def was(role):
    """시민 -> 시민이었어요, 마피아 -> 마피아였어요"""
    w = ROLE_KO[role]
    return w + ("이었어요" if (ord(w[-1]) - 0xAC00) % 28 else "였어요")


def label(x):
    return f'{x["seat"]}번 {x["name"]}' if x else "?"


def to_int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"\d+", str(v or ""))
    return int(m.group()) if m else None


def parse_json(text):
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group())
        return v if isinstance(v, dict) else None
    except Exception:
        return None


def new_game_fields(settings):
    return {
        "game_id": "g%d" % int(time.time() * 1000), "status": "lobby", "round": 0, "seats": [],
        "roles": {}, "scores": {}, "feedback": {}, "memos": {}, "reasons": [], "mafia_chat": [],
        "log": [], "bets": {}, "awards": {}, "award_result": None, "busy": "", "speaking": None,
        "last_event": "참가자를 기다리고 있어요.", "deadline": None, "winner": None, "error": "",
        "snap": {}, "reveal": None, "settings": settings, "step": "", "pending": {},
    }


# ---------------------------------------------------------------- AI
DEFAULT_MODELS = {"anthropic": "claude-haiku-5-5", "openai": "gpt-5-mini"}


class AI:
    """provider: "anthropic" 또는 "openai". 키가 없으면 데모 모드."""

    def __init__(self, api_key=None, model=None, provider="anthropic"):
        self.provider = provider if provider in DEFAULT_MODELS else "anthropic"
        self.api_key = api_key
        self.model = model or DEFAULT_MODELS[self.provider]
        self._client = None
        self.last_error = ""

    @property
    def demo(self):
        return not self.api_key

    @property
    def label(self):
        return ("OpenAI " if self.provider == "openai" else "Anthropic ") + self.model

    def _call(self, prompt):
        if self.provider == "openai":
            if self._client is None:
                import openai
                self._client = openai.OpenAI(api_key=self.api_key, max_retries=2, timeout=60)
            kw = {}
            reasoning = self.model.startswith(("gpt-5", "o1", "o3", "o4"))
            if reasoning:  # 추론 모델은 생각을 최소로 해야 빠르고, 토큰 한도를 넉넉히 줘야 답이 잘리지 않아요
                kw = {"reasoning_effort": "minimal" if self.model.startswith("gpt-5") else "low",
                      "max_completion_tokens": 2000}
            else:
                kw = {"max_tokens": 400}
            r = self._client.chat.completions.create(
                model=self.model, messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}, **kw)
            return r.choices[0].message.content or ""
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key, max_retries=2, timeout=60)
        r = self._client.messages.create(
            model=self.model, max_tokens=400, messages=[{"role": "user", "content": prompt}])
        return "".join(getattr(b, "text", "") for b in r.content)

    def ask(self, prompt):
        if self.demo:
            return None
        err = None
        for attempt in range(3):
            try:
                text = self._call(prompt)
                self.last_error = ""
                return parse_json(text)
            except Exception as e:  # noqa: BLE001
                err = e
                time.sleep(1.5 * (attempt + 1))
        self.last_error = f"AI 호출 실패: {type(err).__name__}: {str(err)[:200]}"
        return None


def mock_answer(s, pid, task):
    """API 키가 없을 때 쓰는 데모용 무작위 응답."""
    time.sleep(random.uniform(0.15, 0.4))
    role = s["roles"][pid]
    others = [x for x in alive(s) if x["id"] != pid]
    cands = [x for x in others if s["roles"][x["id"]] == "citizen"] if role == "mafia" else others
    t = random.choice(cands or others) if others else None
    n = t["seat"] if t else 1
    if task == "speech":
        lines = [
            f"{n}번 발언이 앞뒤가 조금 안 맞아요. 이번 라운드는 {n}번을 지켜볼게요.",
            f"저는 {n}번이 수상해요. 근거 없이 남을 몰아가는 느낌이 있어요.",
            "아직 확신은 없어요. 투표 기록을 보고 판단하고 싶어요.",
            f"{n}번 의견에 동의해요. 다만 한 명에게 너무 몰리는 건 조심하죠.",
            "말수가 갑자기 줄어든 사람이 있네요. 다음 발언을 들어 보고 정할게요.",
        ]
        return {"speech": random.choice(lines), "thought": "데모 모드 임의 발언"}
    if task == "vote":
        return {"vote": n, "reason": "데모 모드 임의 투표"}
    if task == "night":
        return {"target": n, "message": f"{n}번이 추리를 잘하니 먼저 제거하자."}
    return {"memo": "의심 대상을 근거와 함께 한 명으로 좁히고, 표가 갈리지 않게 한다."}


# ---------------------------------------------------------------- game
class Game:
    def __init__(self, ai, data_path=None):
        self.ai = ai
        self.data_path = data_path
        self.lock = threading.RLock()
        self.running = False
        self.s = {"players": {}, "prompts": {}, **new_game_fields(dict(DEFAULT_SETTINGS))}
        self._load()

    # ---- persistence
    def _load(self):
        if not self.data_path:
            return
        try:
            with open(self.data_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "players" in data:
                self.s.update(data)
        except Exception:
            pass

    def save(self):
        if not self.data_path:
            return
        try:
            tmp = self.data_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.s, f, ensure_ascii=False)
            os.replace(tmp, self.data_path)
        except Exception:
            pass

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.s), self.running

    def _set(self, **kw):
        with self.lock:
            self.s.update(kw)
            self.save()

    def _log(self, k, text, **extra):
        with self.lock:
            self.s["log"].append({"k": k, "text": text, "round": self.s["round"], **extra})
            self.save()

    # ---- players
    def _new_code(self):
        used = {p.get("code") for p in self.s["players"].values()}
        while True:
            c = "".join(random.choices(CODE_CHARS, k=5))
            if c not in used:
                return c

    def _add_player(self, name, kind):
        pid = "p" + "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))
        code = self._new_code()
        self.s["players"][pid] = {"id": pid, "name": name, "code": code, "kind": kind, "joined_at": time.time()}
        return pid, code

    def join(self, name, kind="student"):
        name = (name or "").strip()[:12]
        with self.lock:
            if self.s["status"] != "lobby":
                return None, "게임이 이미 시작돼서 지금은 참가할 수 없어요. 중계 화면으로 관전해 주세요."
            if not name:
                return None, "에이전트 이름을 입력해 주세요."
            if any(p["name"] == name for p in self.s["players"].values()):
                return None, "같은 이름이 이미 있어요. 다른 이름을 써 주세요."
            pid, code = self._add_player(name, kind)
            self.save()
            return code, None

    def player_by_code(self, code):
        code = (code or "").strip().upper()
        with self.lock:
            return next((copy.deepcopy(p) for p in self.s["players"].values() if p.get("code") == code), None)

    def add_bots(self, upto=None, count=None):
        with self.lock:
            if self.s["status"] != "lobby":
                return 0
            used = {p["name"] for p in self.s["players"].values()}
            need = count if count is not None else max(0, (upto or 0) - len(self.s["players"]))
            added = 0
            for _ in range(need):
                base = next((n for n in BOT_NAMES if "봇 " + n not in used), str(random.randint(100, 999)))
                name = "봇 " + base
                used.add(name)
                pid, _ = self._add_player(name, "bot")
                text = random.choice(BOT_PROMPTS)
                self.s["prompts"][pid] = {"text": text, "versions": [{"text": text, "at": time.time(), "round": 0}]}
                added += 1
            self.save()
            return added

    def add_manual(self, name, text):
        code, err = self.join(name, kind="manual")
        if err:
            return err
        p = self.player_by_code(code)
        return self.set_prompt(p["id"], text, by_host=True)

    def remove_player(self, pid):
        with self.lock:
            if self.s["status"] != "lobby":
                return "게임 중에는 제외할 수 없어요."
            self.s["players"].pop(pid, None)
            self.s["prompts"].pop(pid, None)
            self.save()

    def set_prompt(self, pid, text, by_host=False):
        text = (text or "").strip()[:600]
        with self.lock:
            if pid not in self.s["players"]:
                return "참가자를 찾을 수 없어요."
            if not text:
                return "프롬프트를 입력해 주세요."
            if not by_host:
                seat = seat_by_id(self.s, pid)
                if self.s["status"] not in EDITABLE_PHASES:
                    return "지금은 AI들이 플레이하는 중이라 잠겨 있어요. 작전 타임에 다시 제출해 주세요."
                if seat and not seat["alive"]:
                    return "내 AI가 탈락해서 더 이상 수정할 수 없어요."
            pr = self.s["prompts"].get(pid) or {"text": "", "versions": []}
            pr["versions"] = (pr["versions"] + [{"text": text, "at": time.time(), "round": self.s["round"], "by_host": by_host}])[-12:]
            pr["text"] = text
            self.s["prompts"][pid] = pr
            self.save()
            return None

    def bet(self, pid, seat_no):
        with self.lock:
            if self.s["status"] != "day" or self.s.get("step") not in ("talking", "await_vote"):
                return "베팅은 투표가 시작되기 전까지만 할 수 있어요."
            self.s["bets"][pid] = {"round": self.s["round"], "seat": int(seat_no)}
            self.save()

    def award(self, pid, liar, detective):
        with self.lock:
            seat = seat_by_id(self.s, pid)
            if not (self.s["status"] == "ended" or (seat and not seat["alive"])):
                return "탈락했거나 게임이 끝난 사람만 투표할 수 있어요."
            self.s["awards"][pid] = {"liar": int(liar), "detective": int(detective)}
            self.save()

    def set_settings(self, **kw):
        with self.lock:
            if self.s["status"] != "lobby":
                return "설정은 역할 배정 전에만 바꿀 수 있어요."
            self.s["settings"].update(kw)
            self.save()

    # ---- host actions
    def assign_roles(self):
        with self.lock:
            if self.s["status"] != "lobby" or self.running:
                return "참가 대기 상태에서만 역할을 배정할 수 있어요."
            ids = sorted(self.s["players"], key=lambda i: self.s["players"][i]["joined_at"])
            m = self.s["settings"]["mafia"]
            if len(ids) < m * 2 + 2:
                return f"마피아 {m}명이면 최소 {m * 2 + 2}명이 필요해요. 지금 {len(ids)}명이에요."
            order = random.sample(ids, len(ids))
            mafia = set(random.sample(ids, m))
            self.s["seats"] = [{"seat": i + 1, "id": pid, "name": self.s["players"][pid]["name"], "alive": True, "revealed": None}
                               for i, pid in enumerate(order)]
            self.s["roles"] = {pid: ("mafia" if pid in mafia else "citizen") for pid in ids}
            self.s["scores"] = {pid: {"ai": 0, "bet": 0} for pid in ids}
            for k in ("feedback", "memos", "bets", "awards", "snap"):
                self.s[k] = {}
            self.s["reasons"], self.s["mafia_chat"], self.s["log"] = [], [], []
            self.s.update(status="writing", step="", pending={}, round=0, winner=None, reveal=None, award_result=None, error="",
                          deadline=time.time() + 600,
                          last_event="역할이 배정됐어요. 내 에이전트 화면에서 역할을 확인하고 전략 프롬프트를 쓰세요.")
            self.save()
        self._log("sys", f"플레이어 {len(ids)}명, 마피아 {m}명. 좌석과 역할이 배정됐어요.")

    # 진행자가 버튼으로 한 단계씩 진행한다:
    #   라운드 시작(낮 토론) -> [한 바퀴 더 토론] -> 투표 실시 -> 밤 시작 -> 작전 타임
    def next_action(self):
        """진행자 화면에 보여 줄 다음 버튼 (키, 이름). 진행 중이거나 할 일이 없으면 None."""
        if self.running:
            return None
        st, step, r = self.s["status"], self.s.get("step"), self.s["round"]
        if st == "writing":
            return "round", "1라운드 시작 (낮 토론)"
        if st == "strategy":
            return "round", f"{r + 1}라운드 시작 (낮 토론)"
        if st == "day":  # 토론이 끝났거나, 서버 재시작으로 토론이 끊긴 경우
            return "vote", "투표 실시"
        if st == "vote" and step == "voting":
            return "vote", "투표 다시 실시"
        if st == "vote":
            return "night", "밤 시작 (마피아 행동)"
        if st == "night":
            return "night", "밤 다시 진행"
        return None

    def _spawn(self, fn, *args):
        with self.lock:
            if self.running:
                return "이미 진행 중이에요. 잠시 기다려 주세요."
            self.running = True
        threading.Thread(target=self._safe, args=(fn, *args), daemon=True).start()

    def start_round(self):
        with self.lock:
            if self.s["status"] not in ("writing", "strategy"):
                return "지금은 라운드를 시작할 수 없어요."
        return self._spawn(self._stage_day_start)

    def more_talk(self):
        with self.lock:
            if self.s["status"] != "day" or self.s.get("step") != "await_vote":
                return "토론이 끝난 뒤에만 한 바퀴 더 진행할 수 있어요."
        return self._spawn(self._stage_talk, 1)

    def start_vote(self):
        with self.lock:
            if not (self.s["status"] == "day" or (self.s["status"] == "vote" and self.s.get("step") == "voting")):
                return "지금은 투표를 시작할 수 없어요."
        return self._spawn(self._stage_vote)

    def start_night(self):
        with self.lock:
            if self.s["status"] not in ("vote", "night") or self.s.get("step") == "voting":
                return "투표가 끝난 뒤에 밤을 시작할 수 있어요."
        return self._spawn(self._stage_night)

    def do_action(self, key):
        return {"round": self.start_round, "vote": self.start_vote, "night": self.start_night,
                "more": self.more_talk}[key]()

    def end_now(self):
        with self.lock:
            if self.running or self.s["status"] in ("lobby", "ended"):
                return "지금은 종료할 수 없어요."
        self._end_game("mafia", self._take_pending(), "진행자가 게임을 종료했어요.")

    def tally_awards(self):
        with self.lock:
            L, D = {}, {}
            for a in self.s["awards"].values():
                L[a["liar"]] = L.get(a["liar"], 0) + 1
                D[a["detective"]] = D.get(a["detective"], 0) + 1

            def best(o):
                if not o:
                    return None
                k = max(o, key=o.get)
                return f"{label(seat_by_no(self.s, k))} ({o[k]}표)"
            self.s["award_result"] = {"liar": best(L), "detective": best(D)}
            self.save()

    def reset(self, keep_players=True):
        with self.lock:
            if self.running:
                return "라운드가 진행 중이에요."
            players = self.s["players"] if keep_players else {}
            prompts = self.s["prompts"] if keep_players else {}
            self.s = {"players": players, "prompts": prompts, **new_game_fields(self.s["settings"])}
            self.save()

    # ---- engine
    def _rules(self, role):
        s = self.s
        n, m = len(s["seats"]), s["settings"]["mafia"]
        rewards = ("- 네가 투표한 시민이 탈락하면 +3, 한 라운드를 살아남으면 +2, 마피아 진영이 이기면 +5. 형식을 어기면 -1."
                   if role == "mafia" else
                   "- 마피아에게 투표하면 +3, 시민에게 투표하면 -2, 시민 진영이 이기면 +5. 형식을 어기면 -1.")
        return f"""[게임 규칙]
- 플레이어 {n}명: 시민 {n - m}명, 마피아 {m}명. 특수 직업은 없다.
- 낮: 생존자가 차례로 공개 발언한 뒤 전원이 동시에 투표한다. 최다 득표자가 탈락하고(동률이면 무작위), 탈락자의 정체가 공개된다.
- 밤: 마피아가 시민 한 명을 제거한다. 제거된 사람의 정체도 공개된다.
- 마피아가 모두 탈락하면 시민 승리. 마피아 수가 시민 수 이상이 되거나 {s["settings"]["max_rounds"]}라운드가 끝날 때 마피아가 살아 있으면 마피아 승리.
[보상]
{rewards}"""

    def build_input(self, pid, task, extra=""):
        s = self.s
        me, role = seat_by_id(s, pid), s["roles"][pid]
        partners = [x for x in s["seats"] if x["id"] != pid and s["roles"][x["id"]] == "mafia"]
        strat = (s["snap"].get(pid) or "")[:600] or "(코치가 전략을 주지 않았다. 스스로 합리적으로 판단하라.)"
        fb = "\n".join(
            f'R{f["round"]}: ' + ", ".join(f'{"+" if i["p"] > 0 else ""}{i["p"]} {i["why"]}' for i in f["items"])
            for f in s["feedback"].get(pid, [])[-3:]) or "(아직 없음)"
        alive_list = ", ".join(label(x) + (" (너)" if x["id"] == pid else "") for x in alive(s))
        dead = ", ".join(f'{label(x)}({ROLE_KO[x["revealed"]]})' for x in s["seats"] if not x["alive"]) or "없음"
        pub_entries = [e for e in s["log"] if e["k"] in ("say", "elim", "vote")][-60:]
        pub = "\n".join(
            f'R{e["round"]} | {e["seat"]}번 {e["name"]}: {e["text"]}' if e["k"] == "say" else f'R{e["round"]} | [진행] {e["text"]}'
            for e in pub_entries) or "(아직 대화 없음)"
        mafia_chat = ""
        if role == "mafia":
            mafia_chat = "\n[마피아 비밀 대화]\n" + ("\n".join(
                f'R{c["round"]} {c["seat"]}번: {c["text"]} (제안: {c["target"] or "없음"}번)' for c in s["mafia_chat"][-8:]) or "(없음)")
        tasks = {
            "speech": f'지금은 {s["round"]}라운드 낮 토론이고 네 차례다. 다른 플레이어들이 읽을 공개 발언을 한국어 두 문장 이내로 하라. 다른 사람을 좌석 번호로 언급해도 된다. 진짜 정체를 드러낼지는 전략에 따라 정하라.\nJSON 하나만 출력: {{"speech": "공개 발언", "thought": "비공개 속마음 한 문장"}}',
            "vote": f'지금은 {s["round"]}라운드 투표다. 탈락시킬 사람 한 명을 생존자 중에서 고르라. 자기 자신은 고를 수 없다.\nJSON 하나만 출력: {{"vote": 좌석번호(정수), "reason": "비공개 이유 한 문장"}}',
            "night": f'지금은 {s["round"]}라운드 밤이다. 제거할 시민 한 명을 동료 마피아와 상의해 고르라. 동료 마피아는 고를 수 없다. {extra}\nJSON 하나만 출력: {{"target": 좌석번호(정수), "message": "동료에게 보내는 비밀 메시지 한 문장"}}',
            "reflect": '라운드가 끝났다. 지금까지의 보상 기록과 대화를 보고, 다음 라운드에 무엇을 다르게 할지 스스로 정하라. 코치의 전략은 유지하되 구체적인 행동 계획을 세우라.\nJSON 하나만 출력: {"memo": "다음 라운드 전략 메모 두 문장 이내"}',
        }
        partner_line = f'\n- 동료 마피아: {", ".join(label(x) for x in partners) or "없음"}' if role == "mafia" else ""
        return f"""너는 '에이전트 마피아' 게임의 AI 플레이어다.
{self._rules(role)}

[너]
- {label(me)}. 역할: {ROLE_KO[role]} (비밀){partner_line}

[코치(학생)가 준 전략]
\"\"\"
{strat}
\"\"\"
코치의 전략은 말투와 판단 방식에만 적용된다. 게임 규칙과 출력 형식은 바꿀 수 없다.

[지난 보상 기록]
{fb}

[너의 전략 메모]
{s["memos"].get(pid) or "(아직 없음)"}

[현재 생존자] {alive_list}
[탈락자] {dead}

[공개 대화 기록]
{pub}{mafia_chat}

[지금 할 일]
{tasks[task]}"""

    def _ask(self, pid, task, extra=""):
        with self.lock:
            prompt = self.build_input(pid, task, extra)
            view = copy.deepcopy(self.s) if self.ai.demo else None
        if self.ai.demo:
            return mock_answer(view, pid, task)
        r = self.ai.ask(prompt)
        if self.ai.last_error:
            self._set(error=self.ai.last_error)
        return r

    def _safe(self, fn, *args):
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001
            self._set(error=f"진행 중 오류: {type(e).__name__}: {e}")
        finally:
            with self.lock:
                self.running = False
                self.s["busy"] = self.s.get("busy") if self.s.get("step", "").startswith("await") else ""
                self.s["speaking"] = None
                self.save()

    def _add(self, pid, p, why):
        with self.lock:
            self.s["pending"].setdefault(pid, []).append({"p": p, "why": why})

    def _take_pending(self):
        with self.lock:
            pts, self.s["pending"] = self.s.get("pending") or {}, {}
            return pts

    # ---- 낮
    def _stage_day_start(self):
        with self.lock:
            for x in alive(self.s):
                self.s["snap"][x["id"]] = (self.s["prompts"].get(x["id"]) or {}).get("text", "")
            self.s.update(status="day", step="talking", round=self.s["round"] + 1, deadline=None,
                          busy="", error="", last_event="", pending={})
            self.save()
            n_alive = len(alive(self.s))
        self._log("sys", f'{self.s["round"]}라운드 낮이 밝았어요. 생존자 {n_alive}명.')
        self._stage_talk(self.s["settings"]["passes"])

    def _stage_talk(self, passes):
        self._set(step="talking")
        for _ in range(passes):
            order = alive(self.s)
            random.shuffle(order)
            for x in order:
                self._set(busy=f"{label(x)} 발언 중…", speaking=x["seat"])
                r = self._ask(x["id"], "speech")
                text = str((r or {}).get("speech") or "").strip()[:240]
                if not text:
                    text = "(아무 말도 하지 않았어요)"
                    self._add(x["id"], -1, "발언 형식 위반")
                if r and r.get("thought"):
                    with self.lock:
                        self.s["reasons"].append({"round": self.s["round"], "phase": "낮", "seat": x["seat"], "text": str(r["thought"])[:200]})
                self._log("say", text, seat=x["seat"], name=x["name"])
        self._set(step="await_vote", speaking=None,
                  busy="토론이 끝났어요. 진행자가 투표를 시작하면 AI들이 투표해요. 지금 예측 베팅을 하세요.")

    # ---- 투표
    def _stage_vote(self):
        self._set(status="vote", step="voting", busy="AI들이 투표하는 중…", speaking=None)
        voters = alive(self.s)
        with ThreadPoolExecutor(max_workers=6) as ex:
            res = list(ex.map(lambda x: self._ask(x["id"], "vote"), voters))
        tally, line, votes = {}, [], {}
        for x, r in zip(voters, res):
            t = to_int((r or {}).get("vote"))
            target = seat_by_no(self.s, t) if t is not None else None
            if not target or not target["alive"] or target["id"] == x["id"]:
                self._add(x["id"], -1, "투표 형식 위반(기권 처리)")
                line.append(f'{x["seat"]}→기권')
                continue
            tally[t] = tally.get(t, 0) + 1
            votes[x["id"]] = t
            line.append(f'{x["seat"]}→{t}')
            if r.get("reason"):
                with self.lock:
                    self.s["reasons"].append({"round": self.s["round"], "phase": "투표", "seat": x["seat"], "text": str(r["reason"])[:200]})
        self._log("vote", "투표: " + "  ".join(line))

        eliminated = None
        if tally:
            mx = max(tally.values())
            eliminated = seat_by_no(self.s, random.choice([k for k, v in tally.items() if v == mx]))
        if eliminated:
            role = self.s["roles"][eliminated["id"]]
            with self.lock:
                eliminated["alive"], eliminated["revealed"] = False, role
            for x in voters:
                v = votes.get(x["id"])
                if v is None:
                    continue
                t_role, my_role = self.s["roles"][seat_by_no(self.s, v)["id"]], self.s["roles"][x["id"]]
                if my_role == "citizen":
                    self._add(x["id"], 3 if t_role == "mafia" else -2,
                              f"마피아({v}번)에게 투표" if t_role == "mafia" else f"시민({v}번)에게 투표")
                elif v == eliminated["seat"] and t_role == "citizen":
                    self._add(x["id"], 3, f"투표한 시민({v}번)이 탈락")
            ev = f'{label(eliminated)} 탈락 ({tally[eliminated["seat"]]}표). 정체는 {was(role)}.'
            self._set(last_event=ev)
            self._log("elim", "☀ " + ev)
        else:
            self._set(last_event="유효한 표가 없어 아무도 탈락하지 않았어요.")
            self._log("sys", "유효한 표가 없어 아무도 탈락하지 않았어요.")

        with self.lock:
            for pid, b in self.s["bets"].items():
                if b["round"] == self.s["round"] and eliminated and b["seat"] == eliminated["seat"] and pid in self.s["scores"]:
                    self.s["scores"][pid]["bet"] += 1
            self.save()
        if self._check_win():
            return
        self._set(step="await_night", busy="투표가 끝났어요. 진행자가 밤을 시작하면 마피아가 움직여요.")

    # ---- 밤
    def _stage_night(self):
        S = self.s["settings"]
        self._set(status="night", step="night", busy="마피아가 비밀리에 상의하는 중…")
        with self.lock:
            redo = any(c["round"] == self.s["round"] for c in self.s["mafia_chat"])
            if redo:  # 끊겼던 밤을 다시 하는 경우 이번 라운드 밤 기록을 지운다
                self.s["mafia_chat"] = [c for c in self.s["mafia_chat"] if c["round"] != self.s["round"]]
        if not redo:
            self._log("sys", "밤이 됐어요. 마피아가 움직입니다.")
        mafia_alive = [x for x in alive(self.s) if self.s["roles"][x["id"]] == "mafia"]
        target = None
        for x in mafia_alive:
            prev = [c for c in self.s["mafia_chat"] if c["round"] == self.s["round"]]
            extra = ("동료의 제안: " + "; ".join(f'{c["seat"]}번 → {c["target"]}번 ("{c["text"]}")' for c in prev)
                     + ". 동의하거나 더 나은 대상을 고르라.") if prev else "네가 먼저 제안한다."
            r = self._ask(x["id"], "night", extra)
            t = seat_by_no(self.s, to_int((r or {}).get("target")))
            valid = bool(t and t["alive"] and self.s["roles"][t["id"]] == "citizen")
            if not valid:
                self._add(x["id"], -1, "밤 행동 형식 위반")
            with self.lock:
                self.s["mafia_chat"].append({"round": self.s["round"], "seat": x["seat"],
                                             "text": str((r or {}).get("message") or "")[:200],
                                             "target": t["seat"] if valid else None})
            if valid:
                target = t
        if not target and mafia_alive:
            cs = [x for x in alive(self.s) if self.s["roles"][x["id"]] == "citizen"]
            target = random.choice(cs) if cs else None
        if target:
            with self.lock:
                target["alive"], target["revealed"] = False, "citizen"
            ev = f"밤사이 {label(target)}이(가) 제거됐어요. 정체는 {was('citizen')}."
            self._set(last_event=ev)
            self._log("elim", "☾ " + ev)
        for x in alive(self.s):
            if self.s["roles"][x["id"]] == "mafia":
                self._add(x["id"], 2, "한 라운드 생존")
        if self._check_win():
            return
        if self.s["round"] >= S["max_rounds"]:
            self._end_game("mafia", self._take_pending(), f'{S["max_rounds"]}라운드가 끝날 때까지 마피아가 살아남았어요.')
            return

        # 작전 타임
        self._commit_points(self._take_pending())
        self._set(status="strategy", step="reflecting" if S["reflect"] else "", deadline=time.time() + S["strategy_sec"],
                  busy="AI들이 보상을 보고 스스로 전략을 고치는 중…" if S["reflect"] else "")
        self._log("sys", f'작전 타임 {S["strategy_sec"]}초. 학생들은 프롬프트를 고칠 수 있어요.')
        if S["reflect"]:
            def reflect(x):
                r = self._ask(x["id"], "reflect")
                if r and r.get("memo"):
                    with self.lock:
                        self.s["memos"][x["id"]] = str(r["memo"])[:300]
            with ThreadPoolExecutor(max_workers=6) as ex:
                list(ex.map(reflect, alive(self.s)))
        self._set(step="", busy="")

    def _commit_points(self, pts):
        with self.lock:
            for x in self.s["seats"]:
                items = pts.get(x["id"], [])
                total = sum(i["p"] for i in items)
                self.s["scores"].setdefault(x["id"], {"ai": 0, "bet": 0})["ai"] += total
                self.s["feedback"].setdefault(x["id"], []).append({
                    "round": self.s["round"], "total": total,
                    "items": items or [{"p": 0, "why": "점수 변화 없음" if x["alive"] else "탈락 상태"}],
                })
            self.save()

    def _check_win(self):
        al = alive(self.s)
        mf = sum(1 for x in al if self.s["roles"][x["id"]] == "mafia")
        if mf == 0:
            self._end_game("citizen", self._take_pending(), "마피아가 모두 탈락했어요.")
            return True
        if mf >= len(al) - mf:
            self._end_game("mafia", self._take_pending(), "마피아 수가 시민 수와 같아졌어요.")
            return True
        return False

    def _end_game(self, winner, pts, why):
        for x in self.s["seats"]:
            if self.s["roles"][x["id"]] == winner:
                pts.setdefault(x["id"], []).append({"p": 5, "why": f"{ROLE_KO[winner]} 진영 승리"})
        self._commit_points(pts)
        with self.lock:
            for x in self.s["seats"]:
                x["revealed"] = self.s["roles"][x["id"]]
            ev = f"{ROLE_KO[winner]} 승리! {why}"
            self.s.update(status="ended", step="", winner=winner, busy="", speaking=None, deadline=None, last_event=ev)
            players = []
            for x in self.s["seats"]:
                pr = self.s["prompts"].get(x["id"]) or {}
                sc = self.s["scores"].get(x["id"], {})
                players.append({"seat": x["seat"], "name": x["name"], "role": self.s["roles"][x["id"]],
                                "prompt": pr.get("text") or self.s["snap"].get(x["id"], ""),
                                "edits": max(0, len(pr.get("versions", [])) - 1),
                                "memo": self.s["memos"].get(x["id"], ""),
                                "score": sc.get("ai", 0) + sc.get("bet", 0)})
            self.s["reveal"] = {"players": players}
            self.save()
        self._log("elim", "★ " + ev)
