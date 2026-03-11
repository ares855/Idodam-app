import streamlit as st
import pandas as pd
import os
import re
from datetime import date, datetime

# ==========================================
# [1] 데이터 연동 주소 (03월 시트 최적화)
# ==========================================
SCHEDULE_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRDw87NcOVP_WZInl7qmTqfPvFoBr-u4fo95Uoi9rbVo0Dc_puMUTQTa5vMs2yYqqsKFzQ-1tWQdtt4/pub?output=csv"
INFO_URL_EXISTING = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTRtoi3NAX4rUW297nOdfO3XPxCM9GiH1mS0MwO3P-nzrrZZl7x_3AT2JWcBMgFGvTA90XB7_1busOj/pub?output=csv"
INFO_URL_NEW = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSwPFINd9ZeNRBtZJkB30Qd3uQKZ9XPiBjS9jU2Sx61yU7dmLl2FqRHHkjoVF7FIQBQVSKTho7L2n8e/pub?output=csv"

LOG_FILE = "attendance_log.csv"
USER_FILE = "users.csv"
PAYMENT_FILE = "payment_log.csv"

STATUS_OPTIONS = ["미체크", "출석", "결석", "보강", "일정변경"]
TEACHERS_LIST = ["김동규", "한다현", "김희애", "장은비", "정진규", "김은정"]
DATE_FMT = "%Y-%m-%d"

# ==========================================
# [2] 지능형 데이터 처리 엔진
# ==========================================

def load_data(file_path, columns):
    if not os.path.exists(file_path):
        return pd.DataFrame(columns=columns)
    try:
        df = pd.read_csv(file_path)
        if "날짜" in df.columns:
            df["날짜"] = pd.to_datetime(df["날짜"]).dt.strftime(DATE_FMT)
        return df
    except: return pd.DataFrame(columns=columns)

def save_data(df, file_path):
    df.to_csv(file_path, index=False, encoding="utf-8-sig")

def clean_and_split_names(raw_value):
    """
    '허윤혁(16)박지우(16)' 또는 '김민채\n이예진' 형태를 분리하여 
    깨끗한 이름 리스트(['허윤혁', '박지우'])로 반환
    """
    if pd.isna(raw_value) or str(raw_value).strip() in ['', 'nan']: return []
    text = str(raw_value)
    # 1. 괄호와 그 안의 내용(나이 등) 모두 제거
    text = re.sub(r"\(.*?\)", " ", text)
    # 2. 한글 이름(2~4자)만 모두 찾아내기
    names = re.findall(r'[가-힣]{2,4}', text)
    return [n.strip() for n in names if n.strip()]

# ==========================================
# [3] 시간표 시트 분석 로직 (2단 헤더 대응)
# ==========================================

@st.cache_data(ttl=60)
def fetch_sheet(url):
    return pd.read_csv(url)

def build_attendance_from_complex_sheet(target_date, df_raw):
    """
    원장님의 2단 헤더(요일-선생님) 및 시/분 분리 구조를 해석
    """
    days_kor = ["월", "화", "수", "목", "금", "토", "일"]
    today_prefix = days_kor[target_date.weekday()]
    date_str = target_date.strftime(DATE_FMT)
    
    # 헤더 분석 (Row 0: 요일, Row 1: 선생님)
    days_row = df_raw.iloc[0].ffill() # 요일 정보를 오른쪽으로 채움
    teachers_row = df_raw.iloc[1]
    
    # 시간 정보 채우기 (A열 '시' 정보를 아래로 채움)
    df_raw.iloc[2:, 0] = df_raw.iloc[2:, 0].ffill()
    
    new_entries = []
    
    # 오늘 요일에 맞는 선생님 열 찾기
    for col_idx in range(len(df_raw.columns)):
        day_val = str(days_row.iloc[col_idx]).strip()
        teacher_val = str(teachers_row.iloc[col_idx]).strip()
        
        if day_val == today_prefix and teacher_val in TEACHERS_LIST:
            # 해당 열의 데이터 스캔 (3번째 줄부터)
            for row_idx in range(2, len(df_raw)):
                row = df_raw.iloc[row_idx]
                cell_val = row.iloc[col_idx]
                
                # 이름 추출
                names = clean_and_split_names(cell_val)
                if not names: continue
                
                # 시간 조합
                try:
                    h = str(row.iloc[0]).replace("시", "").strip().zfill(2)
                    m = str(row.iloc[1]).replace("분", "").strip().zfill(2)
                    time_str = f"{h}:{m}"
                    
                    for name in names:
                        new_entries.append({
                            "날짜": date_str, "요일": f"{today_prefix}요일", "시간": time_str,
                            "선생님": teacher_val, "아동명": name, "출결상태": "미체크", "특이사항": ""
                        })
                except: continue
                
    return pd.DataFrame(new_entries)

# ==========================================
# [4] 메인 UI 및 시스템 로직
# ==========================================

# 세션 및 로그인 초기화 (기존 로직 동일)
if "df" not in st.session_state: st.session_state.df = load_data(LOG_FILE, ["날짜", "요일", "시간", "선생님", "아동명", "출결상태", "특이사항"])
if "users" not in st.session_state:
    st.session_state.users = load_data(USER_FILE, ["userid", "password", "name", "role", "approved"])
    if st.session_state.users[st.session_state.users["userid"] == "ares855"].empty:
        admin = pd.DataFrame([{"userid": "ares855", "password": "Kimdongkyu1!", "name": "김동규", "role": "관리자", "approved": "Yes"}])
        st.session_state.users = pd.concat([st.session_state.users, admin], ignore_index=True)
        save_data(st.session_state.users, USER_FILE)
if "logged_in" not in st.session_state: st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🏃 아이도담 통합 관리 시스템")
    li_id = st.text_input("아이디")
    li_pw = st.text_input("비밀번호", type="password")
    if st.button("로그인"):
        match = st.session_state.users[st.session_state.users["userid"] == li_id]
        if not match.empty and str(match.iloc[0]["password"]) == str(li_pw):
            st.session_state.logged_in = True
            st.session_state.user_info = match.iloc[0].to_dict()
            st.rerun()
    st.stop()

user = st.session_state.user_info
menu = st.sidebar.radio("메뉴", ["🏠 대시보드", "📝 오늘의 출석부", "💰 수납 관리", "🔍 아동 프로필", "⚙️ 관리자 및 디버그"])

# --- [메뉴 1] 출석부 기능 ---
if menu == "📝 오늘의 출석부":
    st.header(f"📅 {user['name']} 선생님 출석부")
    t_date = st.date_input("날짜 선택", date.today())
    t_date_str = t_date.strftime(DATE_FMT)

    if st.button("🔄 구글 시트에서 새 스케줄 가져오기"):
        try:
            raw_sheet = fetch_sheet(SCHEDULE_URL)
            new_df = build_attendance_from_complex_sheet(t_date, raw_sheet)
            
            # 기존 기록 보호 (중복 체크)
            if not st.session_state.df.empty:
                key_cols = ["날짜", "시간", "선생님", "아동명"]
                existing_keys = set(st.session_state.df[key_cols].apply(tuple, axis=1))
                new_only = new_df[~new_df[key_cols].apply(tuple, axis=1).isin(existing_keys)]
            else: new_only = new_df

            st.session_state.df = pd.concat([st.session_state.df, new_only], ignore_index=True)
            save_data(st.session_state.df, LOG_FILE)
            st.success(f"{len(new_only)}개의 수업이 새로 추가되었습니다.")
            st.rerun()
        except Exception as e: st.error(f"연동 실패: {e}")

    # 출석부 명단 표시
    v_df = st.session_state.df[(st.session_state.df["선생님"] == user["name"]) & (st.session_state.df["날짜"] == t_date_str)].copy()
    if v_df.empty: st.info("등록된 수업이 없습니다.")
    else:
        for idx, row in v_df.sort_values("시간").iterrows():
            with st.expander(f"[{row['시간']}] {row['아동명']} ({row['출결상태']})"):
                c1, c2, c3 = st.columns([2, 5, 1])
                ns = c1.selectbox("상태", STATUS_OPTIONS, index=STATUS_OPTIONS.index(row["출결상태"]), key=f"s{idx}")
                nt = c2.text_input("특이사항", value=str(row["특이사항"]) if pd.notna(row["특이사항"]) else "", key=f"n{idx}")
                if c3.button("저장", key=f"b{idx}"):
                    # 그룹 수업 실시간 동기화 (시간/아동명이 같으면 전체 업데이트)
                    mask = (st.session_state.df["날짜"] == t_date_str) & (st.session_state.df["시간"] == row["시간"]) & (st.session_state.df["아동명"] == row["아동명"])
                    st.session_state.df.loc[mask, ["출결상태", "특이사항"]] = [ns, nt]
                    save_data(st.session_state.df, LOG_FILE); st.success("완료"); st.rerun()

# --- [메뉴 2] 아동 프로필 조회 ---
elif menu == "🔍 아동 프로필":
    st.title("📂 아동 상세 정보")
    # ... (신상카드 연동 로직 동일) ...

# --- [메뉴 3] 관리자 디버그 ---
elif menu == "⚙️ 관리자 및 디버그":
    st.title("🛠️ 시스템 진단")
    if st.button("현재 구글 시트 컬럼 및 상단 데이터 확인"):
        test_df = fetch_sheet(SCHEDULE_URL)
        st.write("컬럼 목록:", test_df.columns.tolist())
        st.dataframe(test_df.head(10))
