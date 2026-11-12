"""에이전트 마피아 - Streamlit 웹앱.

화면 세 개:
  중계 화면   ?view=screen   빔프로젝터용. AI 대화, 플레이어, 리더보드
  내 에이전트 ?view=me       학생용. 이름 등록, 역할 확인, 프롬프트 제출, 베팅
  진행자      ?view=host     교수용. 비밀번호로 보호
"""
import html
import io
import os
import time

import streamlit as st

from engine import AI, EDITABLE_PHASES, Game, ROLE_KO, alive, label, phase_name, seat_by_id

st.set_page_config(page_title="에이전트 마피아", page_icon="🕵️", layout="wide", initial_sidebar_state="collapsed")


def cfg(name, default=None):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name, default)


ANTHROPIC_KEY = cfg("ANTHROPIC_API_KEY")
OPENAI_KEY = cfg("OPENAI_API_KEY")
# PROVIDER를 따로 정하지 않으면 넣어 둔 키를 보고 고른다 (둘 다 있으면 Anthropic)
PROVIDER = (cfg("PROVIDER") or ("anthropic" if ANTHROPIC_KEY else "openai" if OPENAI_KEY else "anthropic")).lower()
API_KEY = OPENAI_KEY if PROVIDER == "openai" else ANTHROPIC_KEY
MODEL = cfg("MODEL")
HOST_PASSWORD = cfg("HOST_PASSWORD")
PUBLIC_URL = cfg("PUBLIC_URL", "")
DATA_PATH = cfg("DATA_PATH", "/tmp/agent_mafia_state.json")


def _version():
    """engine.py 내용과 AI 설정이 바뀌면 값이 달라진다.
    코드가 업데이트되면 새 게임 객체를 만들되, 저장 파일에서 진행 상태를 다시 읽어 와 이어 간다."""
    import hashlib
    h = hashlib.sha256()
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine.py"), "rb") as f:
        h.update(f.read())
    h.update(f"{PROVIDER}|{MODEL}|{API_KEY}".encode())
    return h.hexdigest()[:16]


@st.cache_resource(max_entries=1)
def get_game(version):
    import importlib

    import engine
    engine = importlib.reload(engine)  # 업데이트된 engine.py를 확실히 다시 읽는다
    return engine.Game(engine.AI(API_KEY, MODEL, PROVIDER), data_path=DATA_PATH)


game = get_game(_version())
esc = html.escape

# ------------------------------------------------------------------ style
st.markdown("""
<style>
@import url("https://fonts.googleapis.com/css2?family=Black+Han+Sans&family=IBM+Plex+Sans+KR:wght@400;500;700&family=IBM+Plex+Mono:wght@500;600&display=swap");
:root{--ink:#141829;--muted:#5b6278;--line:#d6dae4;--sunk:#f3f4f8;--day:#b45f07;--night:#3043c4;--mafia:#b31d39;--citizen:#1d7650;--warn:#9a6a00}
.stApp,.stApp p,.stApp li,.stApp label,.stApp input,.stApp textarea,.stApp button,.stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp h5{font-family:"IBM Plex Sans KR","Apple SD Gothic Neo","Malgun Gothic",sans-serif}
[data-testid="stHeader"]{display:none}
.block-container{padding-top:1.6rem;max-width:1400px}
.am-brand{font-family:"Black Han Sans","IBM Plex Sans KR",sans-serif;font-size:2rem;line-height:1.1;color:var(--ink)}
.am-brand b{font-weight:400;color:var(--night)}
.am-phase{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;padding:12px 16px;border-radius:10px;border:1px solid var(--line);background:#fff;margin-bottom:12px}
.am-pill{display:inline-flex;align-items:center;gap:8px;padding:4px 14px;border-radius:999px;font-weight:700;color:#fff}
.am-pill.day,.am-pill.writing,.am-pill.lobby{background:var(--day)} .am-pill.vote,.am-pill.night,.am-pill.strategy{background:var(--night)} .am-pill.ended{background:var(--citizen)}
.am-busy{color:var(--muted)} .am-timer{font-family:"IBM Plex Mono",monospace;font-weight:600;font-size:1.1em}
.am-event{font-weight:700;font-size:1.1em;color:var(--ink);margin:0 0 6px}
.am-seats{display:grid;grid-template-columns:repeat(auto-fill,minmax(112px,1fr));gap:8px}
.am-seat{border:1px solid var(--line);border-radius:8px;padding:8px 10px;background:var(--sunk);min-width:0}
.am-seat .n{font-family:"IBM Plex Mono",monospace;font-weight:600}
.am-seat .nm{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.am-seat.dead{opacity:.5}.am-seat.dead .nm{text-decoration:line-through}
.am-seat.speaking{border-color:var(--night);box-shadow:0 0 0 2px rgba(48,67,196,.3);background:#fff}
.am-tag{display:inline-block;font-size:.72em;font-weight:700;padding:1px 7px;border-radius:999px;border:1px solid currentColor}
.am-tag.mafia{color:var(--mafia)}.am-tag.citizen{color:var(--citizen)}.am-tag.out{color:var(--muted)}
.am-feed{display:flex;flex-direction:column-reverse;max-height:64vh;overflow-y:auto;border:1px solid var(--line);border-radius:10px;padding:4px 14px;background:#fff}
.am-round{font-family:"Black Han Sans",sans-serif;color:var(--night);padding:10px 0 2px}
.am-msg{display:grid;grid-template-columns:38px minmax(0,1fr);gap:10px;padding:7px 0;border-bottom:1px dashed var(--line);color:var(--ink)}
.am-msg .who{font-family:"IBM Plex Mono",monospace;font-weight:600;color:var(--night);text-align:right}
.am-msg .mn{font-weight:700;font-size:.85em;color:var(--muted)}
.am-sys{text-align:center;color:var(--muted);font-size:.9em;padding:8px 0}
.am-vote{font-family:"IBM Plex Mono",monospace;font-size:.85em;color:var(--muted);padding:6px 0}
.am-elim{background:rgba(179,29,57,.08);border-radius:8px;padding:10px 12px;font-weight:600;margin:4px 0;color:var(--ink)}
.am-empty{color:var(--muted);text-align:center;padding:24px 4px}
table.am-lb{width:100%;border-collapse:collapse;font-size:.95em}
table.am-lb th{text-align:left;font-size:.75em;color:var(--muted);padding:4px;border-bottom:1px solid var(--line)}
table.am-lb td{padding:6px 4px;border-bottom:1px solid var(--line);color:var(--ink)}
table.am-lb .r{text-align:right;font-family:"IBM Plex Mono",monospace}
.am-role{border-radius:10px;padding:18px;color:#fff;margin-bottom:8px}
.am-role.mafia{background:var(--mafia)}.am-role.citizen{background:var(--citizen)}
.am-role .big{font-family:"Black Han Sans",sans-serif;font-size:2.2em;line-height:1.1}
.am-lock{display:inline-block;font-weight:700;font-size:.85em;padding:3px 10px;border-radius:999px}
.am-lock.open{color:var(--citizen);background:rgba(29,118,80,.12)}.am-lock.shut{color:var(--muted);background:var(--sunk)}
.am-fb{display:grid;grid-template-columns:48px minmax(0,1fr);gap:6px;font-size:.92em;color:var(--ink)}
.am-fb .p{font-family:"IBM Plex Mono",monospace;font-weight:600;text-align:right}
.am-fb .p.plus{color:var(--citizen)}.am-fb .p.minus{color:var(--mafia)}
.am-memo{background:var(--sunk);border-left:3px solid var(--night);padding:10px 12px;border-radius:0 8px 8px 0;color:var(--ink)}
.am-code{font-family:"IBM Plex Mono",monospace;font-size:1.6em;font-weight:600;letter-spacing:.15em;color:var(--ink)}
.am-card{border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:var(--sunk);color:var(--ink);height:100%}
.am-card pre{white-space:pre-wrap;word-break:break-word;font-family:inherit;font-size:.88em;margin:6px 0 0}
.am-steps{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:0 0 10px}
.am-step{padding:4px 12px;border-radius:999px;border:1px solid var(--line);color:var(--muted);font-weight:600;font-size:.9em;background:#fff}
.am-step.now{background:var(--night);border-color:var(--night);color:#fff}
.am-step.done{color:var(--ink);background:var(--sunk)}
.am-arrow{color:var(--muted)}
body.am-big .am-msg,body.am-big table.am-lb{font-size:1.25em}
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------ shared bits
def phase_bar(s, running):
    st_ = s["status"]
    pill = (f'{s["round"]}라운드 · ' if s["round"] else "") + phase_name(s)
    timer = ""
    if s.get("deadline") and st_ in ("writing", "strategy"):
        left = max(0, int(s["deadline"] - time.time()))
        timer = f'<span class="am-timer">남은 시간 {left // 60}:{left % 60:02d}</span>'
    busy = esc(s.get("busy") or "")
    st.markdown(f'<div class="am-phase"><span class="am-pill {st_}">{esc(pill)}</span>{timer}<span class="am-busy">{busy}</span></div>',
                unsafe_allow_html=True)


def seats_html(s):
    if not s["seats"]:
        names = "".join(f'<div class="am-seat"><div class="n">–</div><div class="nm">{esc(p["name"])}</div></div>'
                        for p in sorted(s["players"].values(), key=lambda p: p["joined_at"]))
        return f'<div class="am-seats">{names}</div>' if names else '<div class="am-empty">참가자를 기다리는 중이에요.</div>'
    out = []
    for x in s["seats"]:
        cls = "am-seat" + ("" if x["alive"] else " dead") + (" speaking" if s.get("speaking") == x["seat"] else "")
        if x.get("revealed"):
            tag = f'<span class="am-tag {x["revealed"]}">{ROLE_KO[x["revealed"]]}{"" if x["alive"] else " · 탈락"}</span>'
        else:
            tag = f'<span class="am-tag out">{"생존" if x["alive"] else "탈락"}</span>'
        out.append(f'<div class="{cls}"><div class="n">{x["seat"]}</div><div class="nm">{esc(x["name"])}</div>{tag}</div>')
    return '<div class="am-seats">' + "".join(out) + "</div>"


def feed_html(s):
    parts, last = [], None
    for e in s["log"]:
        if e["round"] != last:
            last = e["round"]
            parts.append(f'<div class="am-round">{str(last) + "라운드" if last else "게임 시작"}</div>')
        if e["k"] == "say":
            parts.append(f'<div class="am-msg"><div class="who">{e["seat"]}</div><div><div class="mn">{esc(e["name"])}</div>{esc(e["text"])}</div></div>')
        else:
            parts.append(f'<div class="am-{e["k"]}">{esc(e["text"])}</div>')
    inner = "".join(parts) or '<div class="am-empty">진행자가 게임을 시작하면 AI들의 대화가 여기에 실시간으로 올라와요.</div>'
    return f'<div class="am-feed"><div>{inner}</div></div>'


def leaderboard_html(s):
    if s["seats"]:
        rows = [{"seat": x["seat"], "name": x["name"], **s["scores"].get(x["id"], {"ai": 0, "bet": 0})} for x in s["seats"]]
    else:
        rows = [{"seat": "–", "name": p["name"], "ai": 0, "bet": 0} for p in s["players"].values()]
    rows.sort(key=lambda r: -(r["ai"] + r["bet"]))
    body = "".join(
        f'<tr><td class="r">{i + 1}</td><td>{r["seat"]}{"번" if r["seat"] != "–" else ""} {esc(r["name"])}</td>'
        f'<td class="r">{r["ai"]}</td><td class="r">{r["bet"]}</td><td class="r"><b>{r["ai"] + r["bet"]}</b></td></tr>'
        for i, r in enumerate(rows)) or '<tr><td colspan="5" class="am-empty">아직 점수가 없어요</td></tr>'
    return ('<table class="am-lb"><thead><tr><th class="r">#</th><th>플레이어</th><th class="r">AI</th>'
            f'<th class="r">예측</th><th class="r">합계</th></tr></thead><tbody>{body}</tbody></table>')


# ------------------------------------------------------------------ screen view
@st.fragment(run_every=2)
def screen_view():
    s, running = game.snapshot()
    phase_bar(s, running)
    c1, c2, c3 = st.columns([1.05, 2.2, 1.15], gap="medium")
    with c1:
        st.markdown("##### 플레이어")
        st.markdown(seats_html(s), unsafe_allow_html=True)
    with c2:
        if s.get("last_event"):
            st.markdown(f'<p class="am-event">{esc(s["last_event"])}</p>', unsafe_allow_html=True)
        st.markdown(feed_html(s), unsafe_allow_html=True)
    with c3:
        st.markdown("##### 리더보드")
        st.markdown(leaderboard_html(s), unsafe_allow_html=True)
    if s["status"] == "ended" and s.get("reveal"):
        reveal_section(s)


def reveal_section(s):
    st.divider()
    st.markdown("### 회고: 프롬프트와 속마음 공개")
    aw = s.get("award_result")
    if aw:
        a, b = st.columns(2)
        a.metric("최고의 거짓말쟁이 AI", aw.get("liar") or "투표 없음")
        b.metric("최고의 탐정 AI", aw.get("detective") or "투표 없음")
    cards = sorted(s["reveal"]["players"], key=lambda p: -p["score"])
    cols = st.columns(3)
    for i, p in enumerate(cards):
        memo = f'<div class="am-memo" style="margin-top:6px;font-size:.88em">AI 메모: {esc(p["memo"])}</div>' if p["memo"] else ""
        cols[i % 3].markdown(
            f'<div class="am-card" style="margin-bottom:10px"><b>{p["seat"]}번 {esc(p["name"])}</b> '
            f'<span class="am-tag {p["role"]}">{ROLE_KO[p["role"]]}</span><br>'
            f'<span style="color:var(--muted);font-size:.85em">점수 {p["score"]} · 프롬프트 수정 {p["edits"]}회</span>'
            f'<pre>{esc(p["prompt"] or "(프롬프트 없음)")}</pre>{memo}</div>', unsafe_allow_html=True)
    a, b = st.columns(2)
    with a:
        st.markdown("##### 마피아 비밀 대화")
        for c in s["mafia_chat"]:
            st.markdown(f'R{c["round"]} · {c["seat"]}번: {esc(c["text"])} → **{str(c["target"]) + "번 제거 제안" if c["target"] else "제안 없음"}**')
    with b:
        st.markdown("##### AI 속마음 (비공개였던 판단 이유)")
        for r in s["reasons"][-60:]:
            st.markdown(f'R{r["round"]} {r["phase"]} · {r["seat"]}번: {esc(r["text"])}')


# ------------------------------------------------------------------ me view
def current_player():
    code = st.query_params.get("p")
    return game.player_by_code(code) if code else None


def me_view():
    me = current_player()
    if not me:
        join_view()
        return
    me_status(me["id"])
    prompt_editor(me)
    with st.expander("내 입장 코드 (다른 기기에서 다시 들어올 때)"):
        st.markdown(f'<div class="am-code">{esc(me["code"])}</div>', unsafe_allow_html=True)
        st.caption("이 페이지 주소를 즐겨찾기해 두거나, 다른 기기의 첫 화면에서 이 코드를 넣으면 다시 들어올 수 있어요.")
        if st.button("이 기기에서 나가기"):
            st.query_params.clear()
            st.query_params["view"] = "me"
            st.rerun()


def join_view():
    s, _ = game.snapshot()
    left, right = st.columns([1.3, 1], gap="large")
    with left:
        st.markdown("### 게임 참가")
        if s["status"] != "lobby":
            st.info("게임이 이미 시작됐어요. 위에서 **중계 화면**을 눌러 관전해 주세요.")
        else:
            st.write("에이전트 이름을 정하고 참가하세요. 게임 중에는 직접 말하지 않고, 내 AI 에이전트에게 줄 전략 프롬프트만 쓸 수 있어요. 로그인은 필요 없어요.")
            with st.form("join"):
                name = st.text_input("에이전트 이름", max_chars=12, placeholder="예: 탐정 셜록")
                if st.form_submit_button("참가하기", type="primary"):
                    code, err = game.join(name)
                    if err:
                        st.error(err)
                    else:
                        st.query_params["p"] = code
                        st.query_params["view"] = "me"
                        st.rerun()
    with right:
        st.markdown("### 다시 들어오기")
        with st.form("rejoin"):
            code = st.text_input("입장 코드", max_chars=5, placeholder="예: K7M2Q")
            if st.form_submit_button("들어가기"):
                if game.player_by_code(code):
                    st.query_params["p"] = code.strip().upper()
                    st.query_params["view"] = "me"
                    st.rerun()
                else:
                    st.error("코드를 찾을 수 없어요. 대소문자와 숫자를 다시 확인해 주세요.")


@st.fragment(run_every=3)
def me_status(pid):
    s, running = game.snapshot()
    phase_bar(s, running)
    if pid not in s["players"]:
        st.warning("진행자가 명단에서 제외했어요. 새로 참가해 주세요.")
        return
    seat = seat_by_id(s, pid)
    role = s["roles"].get(pid)
    name = s["players"][pid]["name"]
    if role:
        if st.toggle("내 역할 보기 (주변 사람이 보지 않을 때 켜 주세요)", key="show_role"):
            partners = [label(x) for x in s["seats"] if x["id"] != pid and s["roles"].get(x["id"]) == "mafia"]
            desc = (f'동료 마피아: {", ".join(partners) or "없음 (혼자예요)"}. 시민인 척 섞여서 살아남는 게 목표예요.'
                    if role == "mafia" else "특별한 정보는 없어요. 대화만 보고 마피아를 찾아야 해요.")
            dead = "<br><b>내 AI는 탈락했어요.</b> 베팅과 시상 투표로 계속 참여할 수 있어요." if seat and not seat["alive"] else ""
            st.markdown(f'<div class="am-role {role}"><div>{seat["seat"]}번 좌석 · {esc(name)}</div>'
                        f'<div class="big">{ROLE_KO[role]}</div><div>{esc(desc)}{dead}</div></div>', unsafe_allow_html=True)
    else:
        st.info(f"**{name}** 님, 참가했어요. 진행자가 역할을 배정하면 여기에 표시돼요. 그동안 아래에서 전략 프롬프트를 미리 써 둘 수 있어요.")

    editable = s["status"] in EDITABLE_PHASES and not (seat and not seat["alive"])
    pr = s["prompts"].get(pid) or {}
    vcount = len(pr.get("versions", []))
    lock = ('<span class="am-lock open">수정 가능</span>' if editable else '<span class="am-lock shut">잠김</span>')
    help_ = ("내 AI가 탈락해서 더 이상 수정할 수 없어요." if seat and not seat["alive"]
             else "작전 타임이에요. 보상을 보고 전략을 고친 뒤 제출하세요. 다음 라운드부터 반영돼요." if s["status"] == "strategy"
             else "역할에 맞는 전략을 써 주세요. 말투, 의심하는 기준, 투표 원칙을 구체적으로 적을수록 좋아요." if editable
             else "AI들이 플레이하는 중이에요. 작전 타임에 다시 열려요.")
    st.markdown(f'{lock} &nbsp; <span style="color:var(--muted)">{esc(help_)} · {"v" + str(vcount) + " 제출됨" if vcount else "아직 제출 전"}</span>',
                unsafe_allow_html=True)

    if s["status"] == "day" and s["round"] and s.get("step") in ("talking", "await_vote"):
        with st.container(border=True):
            st.markdown("**예측 베팅** · 이번 라운드 투표로 누가 탈락할지 맞히면 +1")
            opts = [x["seat"] for x in alive(s)]
            mine = s["bets"].get(pid)
            mine = mine["seat"] if mine and mine["round"] == s["round"] else None
            c1, c2 = st.columns([3, 1])
            pick = c1.selectbox("탈락 예상", opts, format_func=lambda n: label(next(x for x in s["seats"] if x["seat"] == n)),
                                index=opts.index(mine) if mine in opts else 0, label_visibility="collapsed", key=f"bet_{s['round']}")
            if c2.button("베팅하기", key=f"betbtn_{s['round']}"):
                err = game.bet(pid, pick)
                st.toast(err or f"{pick}번에 베팅했어요")
            if mine:
                st.caption(f"{mine}번에 베팅했어요. 투표 전까지 바꿀 수 있어요.")

    fb = s["feedback"].get(pid, [])
    with st.container(border=True):
        st.markdown("**내 AI가 받은 보상**")
        if not fb:
            st.caption("라운드가 끝나면 점수와 이유가 여기에 쌓여요.")
        for f in reversed(fb):
            items = "".join(f'<span class="p {"plus" if i["p"] >= 0 else "minus"}">{"+" if i["p"] > 0 else ""}{i["p"]}</span><span>{esc(i["why"])}</span>'
                            for i in f["items"])
            st.markdown(f'<div style="margin-bottom:8px"><b>{f["round"]}라운드 · 합계 {"+" if f["total"] > 0 else ""}{f["total"]}</b>'
                        f'<div class="am-fb">{items}</div></div>', unsafe_allow_html=True)
        memo = s["memos"].get(pid)
        if memo:
            st.markdown(f'<div class="am-memo"><b>AI가 스스로 쓴 전략 메모</b><br>{esc(memo)}</div>', unsafe_allow_html=True)

    if s["seats"] and (s["status"] == "ended" or (seat and not seat["alive"])):
        with st.container(border=True):
            st.markdown("**시상 투표** · 탈락했거나 게임이 끝난 사람만 투표할 수 있어요")
            opts = [x["seat"] for x in s["seats"]]
            fmt = lambda n: label(next(x for x in s["seats"] if x["seat"] == n))  # noqa: E731
            c1, c2, c3 = st.columns([2, 2, 1])
            liar = c1.selectbox("최고의 거짓말쟁이 AI", opts, format_func=fmt, key="aw_liar")
            det = c2.selectbox("최고의 탐정 AI", opts, format_func=fmt, key="aw_det")
            if c3.button("투표하기", key="aw_btn"):
                st.toast(game.award(pid, liar, det) or "투표했어요")
            if pid in s["awards"]:
                st.caption("투표했어요. 다시 누르면 바뀌어요.")


def prompt_editor(me):
    pid = me["id"]
    s, _ = game.snapshot()
    key = f"prompt_{pid}"
    if key not in st.session_state:
        st.session_state[key] = (s["prompts"].get(pid) or {}).get("text", "")
    with st.form("prompt_form"):
        st.markdown("**내 AI 전략 프롬프트**")
        st.text_area(
            "전략 프롬프트", key=key, height=190, max_chars=600, label_visibility="collapsed",
            placeholder="마피아 예: 평범한 시민처럼 매번 근거 하나를 들어 의견을 낸다. 동료를 대놓고 감싸지 않는다. 투표는 다수가 몰리는 쪽에 함께한다.\n"
                        "시민 예: 발언끼리 모순되는 사람을 찾는다. 근거 없이 몰아가는 사람을 의심한다. 확신이 없으면 말이 가장 많이 바뀐 사람에게 투표한다.")
        if st.form_submit_button("제출하기", type="primary"):
            err = game.set_prompt(pid, st.session_state[key])
            if err:
                st.error(err)
            else:
                st.success("제출했어요. 다음 라운드부터 반영돼요.")


# ------------------------------------------------------------------ host view
def host_view():
    if not HOST_PASSWORD:
        st.warning("진행자 비밀번호(HOST_PASSWORD)가 설정되지 않아 임시 비밀번호 **mafia** 를 쓰고 있어요. 배포 설정의 Secrets에서 꼭 바꿔 주세요.")
    password = HOST_PASSWORD or "mafia"
    if not st.session_state.get("is_host"):
        with st.form("host_login"):
            pw = st.text_input("진행자 비밀번호", type="password")
            if st.form_submit_button("들어가기", type="primary"):
                if pw == password:
                    st.session_state["is_host"] = True
                    st.rerun()
                else:
                    st.error("비밀번호가 맞지 않아요.")
        return

    host_controls()
    st.divider()
    s, _ = game.snapshot()
    lobby = s["status"] == "lobby"
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("#### 참가자 관리")
        with st.container(border=True):
            st.markdown("**학생 대신 등록** · 학생이 보낸 글을 그대로 붙여 넣으면 이름과 프롬프트가 자동으로 나뉘어요")
            with st.form("manual", clear_on_submit=True):
                nm = st.text_input("에이전트 이름 (붙여 넣은 글에 이름이 있으면 비워 두세요)", max_chars=12)
                tx = st.text_area("전략 프롬프트", height=120)
                if st.form_submit_button("등록하기", disabled=not lobby):
                    import re
                    m = re.search(r"이름:\s*(.+)\r?\n전략 프롬프트:\r?\n([\s\S]*)", tx or "")
                    if m:
                        nm, tx = nm or m.group(1).strip(), m.group(2)
                    err = game.add_manual(nm, tx)
                    st.toast(err or f"{nm} 님을 등록했어요")
        with st.container(border=True):
            st.markdown("**봇으로 인원 채우기**")
            b1, b2, b3 = st.columns([2, 1, 1])
            upto = b1.number_input("목표 인원", min_value=4, max_value=30, value=14, label_visibility="collapsed")
            if b2.button("채우기", disabled=not lobby):
                st.toast(f"봇 {game.add_bots(upto=int(upto))}명을 추가했어요")
            if b3.button("봇 1명", disabled=not lobby):
                game.add_bots(count=1)
        players = sorted(s["players"].values(), key=lambda p: p["joined_at"])
        if players:
            with st.container(border=True):
                st.markdown("**프롬프트 대신 입력 / 참가자 제외**")
                pid = st.selectbox("참가자", [p["id"] for p in players], format_func=lambda i: s["players"][i]["name"])
                cur = (s["prompts"].get(pid) or {}).get("text", "")
                with st.form(f"edit_{pid}"):
                    t = st.text_area("프롬프트", value=cur, height=120, max_chars=600)
                    if st.form_submit_button("저장"):
                        st.toast(game.set_prompt(pid, t, by_host=True) or "저장했어요")
                if st.button("이 참가자 제외", disabled=not lobby):
                    st.toast(game.remove_player(pid) or "제외했어요")
                    st.rerun()
    with c2:
        st.markdown("#### 설정")
        cur = s["settings"]
        with st.form("settings"):
            a, b = st.columns(2)
            mafia = a.number_input("마피아 수", 1, 5, int(cur["mafia"]))
            rounds = b.number_input("최대 라운드", 2, 10, int(cur["max_rounds"]))
            passes = a.selectbox("낮 발언 바퀴", [1, 2], index=[1, 2].index(int(cur["passes"])))
            strat = b.selectbox("작전 타임(초)", [30, 60, 90, 120], index=[30, 60, 90, 120].index(int(cur["strategy_sec"])))
            reflect = st.toggle("AI 자기 반성 (보상을 보고 스스로 전략 메모 작성)", value=bool(cur["reflect"]))
            if st.form_submit_button("설정 저장", disabled=not lobby):
                st.toast(game.set_settings(mafia=int(mafia), max_rounds=int(rounds), passes=int(passes),
                                           strategy_sec=int(strat), reflect=bool(reflect)) or "저장했어요")
        if not lobby:
            st.caption("설정은 역할 배정 전에만 바꿀 수 있어요.")
        st.markdown("#### 보상표")
        st.markdown("""
| 행동 | 점수 |
|---|---:|
| 시민이 마피아에게 투표 | +3 |
| 시민이 시민에게 투표 | −2 |
| 마피아가 투표한 시민이 탈락 | +3 |
| 마피아가 한 라운드 생존 | +2 |
| 진영 승리 (생존 여부 무관) | +5 |
| 출력 형식 위반·무응답 | −1 |
| 학생 예측 베팅 적중 | +1 |
""")
        st.markdown("#### 학생 접속 QR")
        url = st.text_input("이 앱의 주소", value=PUBLIC_URL, placeholder="https://....streamlit.app")
        if url:
            try:
                import qrcode
                img = qrcode.make(url.rstrip("/") + "/?view=me")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                st.image(buf.getvalue(), width=260, caption=url.rstrip("/") + "/?view=me")
            except Exception:
                st.code(url.rstrip("/") + "/?view=me")


@st.fragment(run_every=2)
def host_controls():
    s, running = game.snapshot()
    phase_bar(s, running)
    if game.ai.demo:
        st.info("**데모 모드**: AI API 키가 없어 무작위 응답으로 진행해요. 리허설용이에요. 실제 수업 전에 Secrets에 ANTHROPIC_API_KEY 또는 OPENAI_API_KEY를 넣어 주세요.")
    else:
        st.caption(f"AI 모델: {game.ai.label}")
    if s.get("error"):
        st.error(s["error"])
    st_, step = s["status"], s.get("step")
    # 라운드 진행 표시: 낮 토론 → 투표 → 밤 → 작전 타임
    stages = [("day", "낮 토론"), ("vote", "투표"), ("night", "밤"), ("strategy", "작전 타임")]
    cur = [k for k, _ in stages].index(st_) if st_ in [k for k, _ in stages] else -1
    chips = "".join(
        f'<span class="am-step {"now" if i == cur else "done" if i < cur else ""}">{name}</span>' + ('<span class="am-arrow">→</span>' if i < 3 else "")
        for i, (_, name) in enumerate(stages))
    st.markdown(f'<div class="am-steps">{chips}</div>', unsafe_allow_html=True)

    action = game.next_action()
    b = st.columns([1, 1.6, 1.2, 1, 1.2])
    if b[0].button("역할 배정", disabled=running or st_ != "lobby", width="stretch"):
        st.toast(game.assign_roles() or "역할을 배정했어요")
    if action:
        if b[1].button(action[1], type="primary", width="stretch", key=f"act_{action[0]}"):
            st.toast(game.do_action(action[0]) or f"{action[1]}: 시작했어요")
    else:
        b[1].button("AI 진행 중…" if running else "다음 단계 없음", disabled=True, width="stretch", key="act_none")
    if b[2].button("한 바퀴 더 토론", disabled=running or not (st_ == "day" and step == "await_vote"), width="stretch"):
        st.toast(game.more_talk() or "토론을 한 바퀴 더 진행해요")
    if b[3].button("시상 집계", disabled=st_ != "ended", width="stretch"):
        game.tally_awards()
        st.toast("시상 결과를 중계 화면에 공개했어요")
    with b[4].popover("게임 종료 / 초기화", width="stretch"):
        if st.button("지금 게임 종료 (마피아 승리 처리)", disabled=running or st_ in ("lobby", "ended")):
            st.toast(game.end_now() or "게임을 종료했어요")
        if st.button("새 게임으로 초기화 (명단·프롬프트 유지)", disabled=running):
            st.toast(game.reset(keep_players=True) or "초기화했어요")
        if st.button("전부 지우기 (명단까지)", disabled=running):
            st.toast(game.reset(keep_players=False) or "모두 지웠어요")

    rows = []
    roster = ([(x["seat"], x["id"], x["alive"]) for x in s["seats"]] if s["seats"]
              else [("–", p["id"], True) for p in sorted(s["players"].values(), key=lambda p: p["joined_at"])])
    for seat_no, pid, is_alive in roster:
        p = s["players"].get(pid)
        if not p:
            continue
        pr = s["prompts"].get(pid) or {}
        sc = s["scores"].get(pid, {"ai": 0, "bet": 0})
        rows.append({
            "좌석": seat_no, "이름": p["name"],
            "구분": {"bot": "봇", "manual": "대리 등록"}.get(p.get("kind"), "학생"),
            "역할": ROLE_KO.get(s["roles"].get(pid), "–"),
            "상태": "생존" if is_alive else "탈락",
            "프롬프트": f'v{len(pr.get("versions", []))}' if pr.get("text") else "미제출",
            "점수": sc["ai"] + sc["bet"], "입장 코드": p["code"],
        })
    st.markdown(f"**참가자 {len(s['players'])}명** · 역할은 이 화면에서만 보여요. 대리 등록한 학생에게는 역할을 따로 알려 주세요.")
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch", height=36 * (len(rows) + 1) + 4)


# ------------------------------------------------------------------ layout
VIEWS = {"screen": "중계 화면", "me": "내 에이전트", "host": "진행자"}
view = st.query_params.get("view", "me")
if view not in VIEWS:
    view = "me"

head_l, head_r = st.columns([1, 2])
head_l.markdown('<div class="am-brand">에이전트 <b>마피아</b></div>', unsafe_allow_html=True)
picked = head_r.radio("화면", list(VIEWS), index=list(VIEWS).index(view), format_func=VIEWS.get,
                      horizontal=True, label_visibility="collapsed")
if picked != view:
    st.query_params["view"] = picked
    st.rerun()

if view == "screen":
    screen_view()
elif view == "host":
    host_view()
else:
    me_view()
