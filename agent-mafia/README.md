# 에이전트 마피아

학생들이 프롬프트로 자기 AI 에이전트를 코칭하고, AI들끼리 마피아 게임을 하는 수업용 웹앱이에요.
로그인 없이 링크만 있으면 누구나 참가할 수 있어요.

| 화면 | 주소 | 누가 |
|---|---|---|
| 내 에이전트 | `앱주소/?view=me` | 학생. 이름 등록, 역할 확인, 프롬프트 제출, 예측 베팅, 시상 투표 |
| 중계 화면 | `앱주소/?view=screen` | 빔프로젝터. AI 대화, 플레이어, 리더보드, 종료 후 회고 |
| 진행자 | `앱주소/?view=host` | 교수. 비밀번호로 보호. 역할 배정, 라운드 진행, 대리 등록, 설정 |

## 배포하기 (Streamlit Community Cloud, 무료, 약 5분)

1. https://share.streamlit.io 에 GitHub 계정으로 로그인해요.
2. **Create app** → **Deploy a public app from GitHub** 를 눌러요.
3. 아래처럼 입력해요.
   - Repository: `ai-agent-yonsei/agent`
   - Branch: `agent-mafia`
   - Main file path: `agent-mafia/app.py`
   - App URL: 원하는 이름 (예: `agent-mafia-yonsei` → `https://agent-mafia-yonsei.streamlit.app`)
4. **Advanced settings** 를 열어요.
   - Python version: 3.12
   - Secrets 칸에 아래를 붙여 넣고 값을 바꿔요.
     Anthropic(Claude)을 쓸 때:
     ```toml
     ANTHROPIC_API_KEY = "sk-ant-..."
     HOST_PASSWORD = "진행자-비밀번호"
     PUBLIC_URL = "https://agent-mafia-yonsei.streamlit.app"
     ```
     OpenAI를 쓸 때:
     ```toml
     OPENAI_API_KEY = "sk-..."
     HOST_PASSWORD = "진행자-비밀번호"
     PUBLIC_URL = "https://agent-mafia-yonsei.streamlit.app"
     ```
     넣은 키에 따라 자동으로 골라요. 둘 다 넣으면 Anthropic을 쓰고, `PROVIDER = "openai"`를 추가하면 OpenAI로 바뀌어요.
     모델을 바꾸려면 `MODEL = "gpt-4o-mini"`처럼 적어요. 기본값은 Anthropic `claude-haiku-5-5`, OpenAI `gpt-5-mini`예요.
5. **Deploy** 를 누르면 1~3분 뒤에 앱이 열려요.

API 키가 없으면 **데모 모드**로 돌아가요. AI 대신 무작위 응답으로 진행되니 리허설용으로 쓰세요.
API 키는 Anthropic은 https://console.anthropic.com , OpenAI는 https://platform.openai.com/api-keys 에서 만들 수 있어요.

## 수업 진행 순서

1. 진행자 화면에 들어가 비밀번호를 넣어요. 화면 아래에 학생 접속용 QR 코드가 나와요.
2. 학생들이 QR로 들어와 에이전트 이름을 정하고 참가해요. 입장 코드가 생기니 다른 기기에서도 다시 들어올 수 있어요.
3. 인원이 모자라면 **봇으로 인원 채우기**를 눌러요.
4. **역할 배정**을 누르면 학생 화면에 역할이 뜨고 10분 동안 프롬프트를 써요.
5. 라운드는 진행자가 버튼으로 한 단계씩 넘겨요.
   - **라운드 시작 (낮 토론)**: AI들이 차례로 발언하고 멈춰요. 이때 학생들은 탈락 예측 베팅을 해요.
     토론이 부족하면 **한 바퀴 더 토론**을 눌러요.
   - **투표 실시**: AI 전원이 투표하고 탈락자와 정체가 공개된 뒤 멈춰요.
   - **밤 시작 (마피아 행동)**: 마피아 AI들이 비밀리에 상의해 한 명을 제거하고 작전 타임으로 넘어가요.
   각 단계는 서버에서 돌아가므로 진행자 화면을 닫아도 그 단계는 끝까지 진행돼요.
6. 작전 타임에 학생들이 프롬프트를 고치면 다음 라운드 시작을 눌러요.
7. 게임이 끝나면 중계 화면에 모든 프롬프트, AI 속마음, 마피아 비밀 대화가 공개돼요.
   탈락자와 참가자가 시상 투표를 하면 **시상 집계**를 눌러요.

## 알아둘 점

- 게임 상태는 서버 메모리와 임시 파일에 저장돼요. 무료 Streamlit 앱은 한동안 접속이 없으면 잠들고,
  깨어나면 상태가 초기화될 수 있어요. 수업 직전에 한 번 접속해서 깨워 두세요.
- 앱 하나에서 게임 하나가 돌아가요. 두 반을 동시에 하려면 앱을 두 개 배포하세요.
- AI 호출은 14명, 5라운드 기준 한 판에 약 300회예요. 쓰는 회사의 콘솔에서 월 사용 한도를 정해 두면 안심이에요.
- 진행자 화면은 새로고침하면 비밀번호를 다시 넣어야 해요.

## 로컬에서 실행

```bash
pip install -r requirements.txt
ANTHROPIC_API_KEY=sk-ant-... HOST_PASSWORD=1234 streamlit run app.py
```
