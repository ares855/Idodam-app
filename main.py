import streamlit as st
import pandas as pd
import os
import re
from datetime import date

# ==========================================
# [1] 기본 설정
# ==========================================
SCHEDULE_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRDw87NcOVP_WZInl7qmTqfPvFoBr-u4fo95Uoi9rbVo0Dc_puMUTQTa5vMs2yYqqsKFzQ-1tWQdtt4/pub?output=csv"
INFO_URL_EXISTING = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTRtoi3NAX4rUW297nOdfO3XPxCM9GiH1mS0MwO3P-nzrrZZl7x_3AT2JWcBMgFGvTA90XB7_1busOj/pub?output=csv"
INFO_URL_NEW = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSwPFINd9ZeNRBtZJkB30Qd3uQKZ9XPiBjS9jU2Sx61yU7dmLl2FqRHHkjoVF7FIQBQVSKTho7L2n8e/pub?output=csv"

LOG_FILE = "attendance_log.csv"
USER_FILE = "users.csv"
PAYMENT_FILE = "payment_log.csv"
PARKING_FILE = "parking_log.csv"

DATE_FMT = "%Y-%m-%d"
STATUS_OPTIONS = ["미체크", "출석", "결석", "보강", "일정변경"]


# ==========================================
# [2] 공통 유틸
# ==========================================
def normalize_date(value):
    try:
        return pd.to_datetime(value).strftime(DATE_FMT)
    except Exception:
        return ""


def load_data(file_path, columns):
    if not os.path.exists(file_path):
        return pd.DataFrame(columns=columns)

    try:
        df = pd.read_csv(file_path)
        if "날짜" in df.columns:
            df["날짜"] = df["날짜"].apply(normalize_date)
        if "수업일자" in df.columns:
            df["수업일자"] = df["수업일자"].apply(normalize_date)
        return df
    except Exception as e:
        st.error(f"{file_path} 불러오기 실패: {e}")
        return pd.DataFrame(columns=columns)


def save_data(df, file_path):
    df.to_csv(file_path, index=False, encoding="utf-8-sig")


def get_day_prefix(target_date):
    days_kor = ["월", "화", "수", "목", "금", "토", "일"]
    return days_kor[target_date.weekday()]


def normalize_name_column(df):
    """
    이름 컬럼을 '성명'으로 표준화
    """
    candidate_cols = ["성명", "이름", "학생 이름", "아동명", "성함", "이용자명", "이름(성명)"]

    for col in candidate_cols:
        if col in df.columns:
            return df.rename(columns={col: "성명"})

    for col in df.columns:
        col_str = str(col).strip()
        if any(keyword in col_str for keyword in ["성명", "이름", "아동"]):
            return df.rename(columns={col: "성명"})

    raise ValueError(f"이름 컬럼을 찾을 수 없습니다. 현재 컬럼: {list(df.columns)}")


def clean_child_names(raw_value):
    """
    아동명 정제
    - 빈칸, nan, -, 없음 등은 무시
    - 괄호 제거
    - 날짜 제거
    - / , + 구분자로 복수 이름 분리
    - 실제 이름처럼 보이는 값만 남김
    """
    if pd.isna(raw_value):
        return []

    text = str(raw_value).strip()
    if not text:
        return []

    invalid_values = {
        "nan", "none", "-", "--", "---", "없음", "없음.", "미정", "공란", "빈칸"
    }
    if text.lower() in invalid_values:
        return []

    text = re.sub(r"\(.*?\)", "", text)
    text = re.sub(r"\b\d{1,2}/\d{1,2}\b", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return []

    parts = re.split(r"[/,+]", text)

    names = []
    for p in parts:
        name = p.strip()

        if not name:
            continue

        if not re.search(r"[가-힣A-Za-z]", name):
            continue

        if len(name) < 2:
            continue

        names.append(name)

    return names


def get_profile_value(row, candidates, default=""):
    for col in candidates:
        value = row.get(col)
        if pd.notna(value) and str(value).strip():
            return str(value).strip()
    return default


# ==========================================
# [3] 외부 데이터 가져오기
# ==========================================
@st.cache_data(ttl=60)
def fetch_sheet(url, header="infer"):
    if header is None:
        return pd.read_csv(url, header=None)
    return pd.read_csv(url)


@st.cache_data(ttl=60)
def fetch_profile_sheets():
    df1 = pd.read_csv(INFO_URL_EXISTING)
    df2 = pd.read_csv(INFO_URL_NEW)
    return df1, df2


def get_profiles():
    df1, df2 = fetch_profile_sheets()
    df1 = normalize_name_column(df1)
    df2 = normalize_name_column(df2)

    profiles = pd.concat([df1, df2], ignore_index=True, sort=False)
    profiles["성명"] = profiles["성명"].fillna("").astype(str).str.strip()
    profiles = profiles[profiles["성명"] != ""]
    return profiles


# ==========================================
# [4] 아이도담 시간표 전용 파서
# ==========================================
def build_attendance_entries(target_date, df_sheet):
    """
    아이도담 시간표 전용
    header=None 기준
    가정:
    - 0행: 요일 블록 (월/화/수/목/금/토)
    - 1행: 선생님 이름
    - 2행 이후: 실제 수업 데이터
    - 0열: 시
    - 1열: 분
    """
    if df_sheet.empty or df_sheet.shape[0] < 3:
        raise ValueError("시간표 데이터가 너무 짧습니다. 최소 3행 이상 필요합니다.")

    day_prefix = get_day_prefix(target_date)
    date_str = target_date.strftime(DATE_FMT)

    df_sheet = df_sheet.copy()

    # 첫 번째 열(시) 빈칸 채우기
    df_sheet.iloc[:, 0] = df_sheet.iloc[:, 0].ffill()

    day_row = df_sheet.iloc[0]
    teacher_row = df_sheet.iloc[1]
    body = df_sheet.iloc[2:].copy()

    today_cols = []
    current_day = None

    for col_idx in range(df_sheet.shape[1]):
        top_value = str(day_row.iloc[col_idx]).strip()

        if top_value and top_value.lower() != "nan":
            current_day = top_value

        if current_day == day_prefix:
            today_cols.append(col_idx)

    if not today_cols:
        raise ValueError(f"{day_prefix}요일 컬럼 블록을 찾지 못했습니다. 시간표 원본 구조를 다시 확인해 주세요.")

    new_entries = []
    parse_errors = []

    for col_idx in today_cols:
        if col_idx < 2:
            continue

        teacher_name = str(teacher_row.iloc[col_idx]).strip()
        if not teacher_name or teacher_name.lower() == "nan":
            continue

        for row_idx, row in body.iterrows():
            child_raw = row.iloc[col_idx]
            children = clean_child_names(child_raw)

            if not children:
                continue

            hour_raw = row.iloc[0]
            minute_raw = row.iloc[1]

            try:
                hour_text = str(hour_raw).replace("시", "").strip()
                minute_text = str(minute_raw).replace("분", "").strip()

                hour = str(int(float(hour_text))).zfill(2)
                minute = str(int(float(minute_text))).zfill(2)
                time_str = f"{hour}:{minute}"
            except Exception as e:
                parse_errors.append(f"행 {row_idx + 1}, 열 {col_idx}, 교사 {teacher_name}: {e}")
                continue

            for child_name in children:
                new_entries.append({
                    "날짜": date_str,
                    "요일": f"{day_prefix}요일",
                    "시간": time_str,
                    "선생님": teacher_name,
                    "아동명": child_name,
                    "출결상태": "미체크",
                    "특이사항": ""
                })

    return pd.DataFrame(new_entries), parse_errors


def merge_new_schedule(existing_df, new_df):
    key_cols = ["날짜", "시간", "선생님", "아동명"]

    if new_df.empty:
        return existing_df, 0

    if existing_df.empty:
        merged = pd.concat([existing_df, new_df], ignore_index=True)
        return merged, len(new_df)

    existing_keys = set(existing_df[key_cols].apply(tuple, axis=1))
    new_only = new_df[~new_df[key_cols].apply(tuple, axis=1).isin(existing_keys)].copy()

    merged = pd.concat([existing_df, new_only], ignore_index=True)
    return merged, len(new_only)


# ==========================================
# [5] 세션 초기화
# ==========================================
if "df" not in st.session_state:
    st.session_state.df = load_data(
        LOG_FILE,
        ["날짜", "요일", "시간", "선생님", "아동명", "출결상태", "특이사항"]
    )

if "users" not in st.session_state:
    st.session_state.users = load_data(
        USER_FILE,
        ["userid", "password", "name", "role", "approved"]
    )

    # 운영 시 비밀번호 해시 저장 권장
    if st.session_state.users[st.session_state.users["userid"] == "ares855"].empty:
        admin_df = pd.DataFrame([{
            "userid": "ares855",
            "password": "Kimdongkyu1!",
            "name": "김동규",
            "role": "관리자",
            "approved": "Yes"
        }])
        st.session_state.users = pd.concat([st.session_state.users, admin_df], ignore_index=True)
        save_data(st.session_state.users, USER_FILE)

if "payments" not in st.session_state:
    st.session_state.payments = load_data(
        PAYMENT_FILE,
        ["아동명", "수납상태", "금액", "결제일", "비고"]
    )

if "parking" not in st.session_state:
    st.session_state.parking = load_data(
        PARKING_FILE,
        ["등록일시", "수업일자", "아동명", "차량번호", "등록교사", "비고"]
    )

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "last_parse_errors" not in st.session_state:
    st.session_state["last_parse_errors"] = []


# ==========================================
# [6] 로그인
# ==========================================
if not st.session_state.logged_in:
    st.title("🏃 아이도담 통합 관리 시스템")

    login_id = st.text_input("아이디")
    login_pw = st.text_input("비밀번호", type="password")

    if st.button("로그인"):
        users_df = st.session_state.users
        match = users_df[users_df["userid"] == login_id]

        if match.empty:
            st.error("존재하지 않는 아이디입니다.")
        elif str(match.iloc[0]["password"]) != str(login_pw):
            st.error("비밀번호가 일치하지 않습니다.")
        elif str(match.iloc[0]["approved"]) == "No":
            st.warning("원장님의 승인이 필요한 계정입니다.")
        else:
            st.session_state.logged_in = True
            st.session_state.user_info = match.iloc[0].to_dict()
            st.rerun()

    st.stop()


# ==========================================
# [7] 메뉴
# ==========================================
user = st.session_state.user_info
is_admin = (user["userid"] == "ares855")

menu_options = [
    "🏠 대시보드",
    "📝 오늘의 출석부",
    "💰 수납 관리",
    "🔍 아동 프로필",
    "🚗 주차 등록",
    "📋 출결 조회"
]
if is_admin:
    menu_options.append("⚙️ 관리자 및 디버그")

menu = st.sidebar.radio("메뉴 선택", menu_options)


# ==========================================
# [8] 대시보드
# ==========================================
if menu == "🏠 대시보드":
    st.title("🏃 아이도담 대시보드")

    today_str = date.today().strftime(DATE_FMT)
    today_df = st.session_state.df[st.session_state.df["날짜"] == today_str]

    c1, c2, c3 = st.columns(3)
    c1.metric("오늘 수업", len(today_df))
    c2.metric("출석", len(today_df[today_df["출결상태"] == "출석"]))
    c3.metric("미체크", len(today_df[today_df["출결상태"] == "미체크"]))

    st.subheader("오늘 수업 현황")
    if not today_df.empty:
        st.dataframe(today_df.sort_values(by=["시간", "선생님", "아동명"]), use_container_width=True)
    else:
        st.info("오늘 등록된 수업이 없습니다.")


# ==========================================
# [9] 오늘의 출석부
# ==========================================
elif menu == "📝 오늘의 출석부":
    st.header(f"📅 {user['name']} 선생님 출석부")

    target_date = st.date_input("날짜 선택", date.today())
    target_date_str = target_date.strftime(DATE_FMT)

    if st.button("🔄 구글 시트에서 새 스케줄 동기화"):
        try:
            raw_sheet = fetch_sheet(SCHEDULE_URL, header=None)
            new_df, parse_errors = build_attendance_entries(target_date, raw_sheet)

            merged_df, added_count = merge_new_schedule(st.session_state.df, new_df)
            st.session_state.df = merged_df
            save_data(st.session_state.df, LOG_FILE)

            st.session_state["last_parse_errors"] = parse_errors

            if added_count > 0:
                st.success(f"{added_count}개의 새 수업을 추가했습니다.")
            else:
                st.info("새로 추가된 수업이 없습니다.")

            if parse_errors:
                st.warning(f"시간 파싱 실패 {len(parse_errors)}건이 있습니다. 관리자 디버그 탭에서 확인하세요.")

            st.rerun()

        except Exception as e:
            st.error(f"시간표 동기화 실패: {e}")

    view_df = st.session_state.df[
        (st.session_state.df["선생님"] == user["name"]) &
        (st.session_state.df["날짜"] == target_date_str)
    ].copy()

    if view_df.empty:
        st.info("등록된 수업이 없습니다.")
    else:
        view_df["정렬시간"] = pd.to_datetime(view_df["시간"], format="%H:%M", errors="coerce")
        view_df = view_df.sort_values(by=["정렬시간", "아동명"])

        for idx, row in view_df.iterrows():
            with st.expander(f"[{row['시간']}] {row['아동명']} ({row['출결상태']})"):
                c1, c2, c3 = st.columns([2, 5, 1])

                current_status = row["출결상태"] if row["출결상태"] in STATUS_OPTIONS else "미체크"
                new_status = c1.selectbox(
                    "상태",
                    STATUS_OPTIONS,
                    index=STATUS_OPTIONS.index(current_status),
                    key=f"status_{idx}"
                )

                note_value = "" if pd.isna(row["특이사항"]) else str(row["특이사항"])
                new_note = c2.text_input("특이사항", value=note_value, key=f"note_{idx}")

                if c3.button("저장", key=f"save_{idx}"):
                    # 공동 수업 동기화
                    mask = (
                        (st.session_state.df["날짜"] == target_date_str) &
                        (st.session_state.df["시간"] == row["시간"]) &
                        (st.session_state.df["아동명"] == row["아동명"])
                    )
                    st.session_state.df.loc[mask, ["출결상태", "특이사항"]] = [new_status, new_note]
                    save_data(st.session_state.df, LOG_FILE)
                    st.success("저장되었습니다.")
                    st.rerun()


# ==========================================
# [10] 수납 관리
# ==========================================
elif menu == "💰 수납 관리":
    st.title("💰 수납 현황 관리")

    if is_admin:
        with st.expander("수납 파일 업로드"):
            up_file = st.file_uploader("엑셀 또는 CSV 업로드", type=["xlsx", "csv"])
            if up_file is not None:
                try:
                    if up_file.name.endswith(".xlsx"):
                        payment_df = pd.read_excel(up_file)
                    else:
                        payment_df = pd.read_csv(up_file)

                    st.session_state.payments = payment_df
                    save_data(payment_df, PAYMENT_FILE)
                    st.success("수납 데이터가 업데이트되었습니다.")
                except Exception as e:
                    st.error(f"수납 파일 처리 실패: {e}")

    search_name = st.text_input("아동명 검색")
    display_df = st.session_state.payments.copy()

    if "아동명" in display_df.columns:
        display_df["아동명"] = display_df["아동명"].fillna("").astype(str)
        if search_name:
            display_df = display_df[display_df["아동명"].str.contains(search_name, na=False)]

    st.dataframe(display_df, use_container_width=True)


# ==========================================
# [11] 아동 프로필
# ==========================================
elif menu == "🔍 아동 프로필":
    st.title("📂 아동 상세 프로필")

    try:
        profiles = get_profiles()

        if profiles.empty:
            st.warning("불러온 프로필 데이터가 없습니다.")
        else:
            child_list = sorted(profiles["성명"].dropna().astype(str).str.strip().unique())
            selected_child = st.selectbox("아동 선택", child_list)

            if selected_child:
                d = profiles[profiles["성명"] == selected_child].iloc[0]

                with st.expander("원본 프로필 전체 보기", expanded=True):
                    display_series = d.dropna()
                    st.dataframe(display_series.to_frame(name="내용"), use_container_width=True)

    except Exception as e:
        st.error(f"신상 정보 로딩 실패: {e}")


# ==========================================
# [12] 주차 등록
# ==========================================
elif menu == "🚗 주차 등록":
    st.title("🚗 주차 등록")

    try:
        profiles = get_profiles()

        if profiles.empty:
            st.warning("프로필 데이터를 불러올 수 없습니다.")
        else:
            child_list = sorted(profiles["성명"].dropna().astype(str).str.strip().unique())

            c1, c2 = st.columns([2, 1])
            selected_child = c1.selectbox("아동 선택", child_list)
            parking_date = c2.date_input("수업일자", date.today())

            if selected_child:
                d = profiles[profiles["성명"] == selected_child].iloc[0]

                car_number = get_profile_value(
                    d,
                    ["이용하시는차량번호", "차량번호", "이용 차량번호", "보호자 차량번호"],
                    default="미등록"
                )

                st.info(f"선택 아동: {selected_child}")
                st.success(f"차량번호: {car_number}")

                memo = st.text_input("비고", placeholder="예: 지하주차장 등록 완료")

                if st.button("주차 등록 저장"):
                    new_row = pd.DataFrame([{
                        "등록일시": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "수업일자": parking_date.strftime(DATE_FMT),
                        "아동명": selected_child,
                        "차량번호": car_number,
                        "등록교사": user["name"],
                        "비고": memo
                    }])

                    st.session_state.parking = pd.concat(
                        [st.session_state.parking, new_row],
                        ignore_index=True
                    )
                    save_data(st.session_state.parking, PARKING_FILE)
                    st.success("주차 등록이 저장되었습니다.")
                    st.rerun()

            st.subheader("최근 주차 등록 내역")
            parking_view = st.session_state.parking.copy()

            if not parking_view.empty:
                parking_view["등록일시_dt"] = pd.to_datetime(parking_view["등록일시"], errors="coerce")
                parking_view = parking_view.sort_values("등록일시_dt", ascending=False).drop(columns=["등록일시_dt"])
                st.dataframe(parking_view.head(30), use_container_width=True)
            else:
                st.info("저장된 주차 등록 내역이 없습니다.")

    except Exception as e:
        st.error(f"주차 등록 기능 오류: {e}")


# ==========================================
# [13] 출결 조회
# ==========================================
elif menu == "📋 출결 조회":
    st.title("📋 아동 출결 조회")

    attendance_df = st.session_state.df.copy()

    if attendance_df.empty:
        st.info("출결 데이터가 없습니다.")
    else:
        child_candidates = sorted(attendance_df["아동명"].dropna().astype(str).str.strip().unique())

        today = date.today()
        start_default = today.replace(day=1)

        c1, c2, c3 = st.columns([2, 1, 1])
        selected_child = c1.selectbox("아동명 선택", child_candidates)
        start_date = c2.date_input("조회 시작일", start_default)
        end_date = c3.date_input("조회 종료일", today)

        df_search = attendance_df.copy()
        df_search["날짜_dt"] = pd.to_datetime(df_search["날짜"], errors="coerce")

        mask = (
            (df_search["아동명"].astype(str).str.strip() == selected_child) &
            (df_search["날짜_dt"] >= pd.to_datetime(start_date)) &
            (df_search["날짜_dt"] <= pd.to_datetime(end_date))
        )

        result_df = df_search[mask].copy()

        st.subheader("조회 결과 요약")

        a1, a2, a3, a4, a5 = st.columns(5)
        a1.metric("전체", len(result_df))
        a2.metric("출석", len(result_df[result_df["출결상태"] == "출석"]))
        a3.metric("결석", len(result_df[result_df["출결상태"] == "결석"]))
        a4.metric("보강", len(result_df[result_df["출결상태"] == "보강"]))
        a5.metric("미체크/기타", len(result_df[~result_df["출결상태"].isin(["출석", "결석", "보강"]) ]))

        if result_df.empty:
            st.info("해당 기간에 조회된 출결 내역이 없습니다.")
        else:
            result_df = result_df.sort_values(by=["날짜_dt", "시간", "선생님"])
            st.dataframe(
                result_df[["날짜", "요일", "시간", "선생님", "아동명", "출결상태", "특이사항"]],
                use_container_width=True
            )


# ==========================================
# [14] 관리자 및 디버그
# ==========================================
elif menu == "⚙️ 관리자 및 디버그":
    st.title("🛠️ 관리자 및 디버그")

    tab1, tab2, tab3 = st.tabs(["가입 승인", "데이터 진단", "사용자 목록"])

    with tab1:
        st.subheader("가입 승인")
        pending = st.session_state.users[st.session_state.users["approved"] == "No"]

        if pending.empty:
            st.info("승인 대기 계정이 없습니다.")
        else:
            for i, u in pending.iterrows():
                c1, c2 = st.columns([4, 1])
                c1.write(f"{u['name']} ({u['userid']})")
                if c2.button("승인", key=f"approve_{i}"):
                    st.session_state.users.at[i, "approved"] = "Yes"
                    save_data(st.session_state.users, USER_FILE)
                    st.success(f"{u['name']} 계정을 승인했습니다.")
                    st.rerun()

    with tab2:
        st.subheader("실시간 데이터 진단")

        if st.button("시간표 시트 구조 확인"):
            try:
                raw_sheet = fetch_sheet(SCHEDULE_URL, header=None)
                st.write("시간표 shape:", raw_sheet.shape)
                st.dataframe(raw_sheet.head(10), use_container_width=True)
            except Exception as e:
                st.error(f"시간표 시트 확인 실패: {e}")

        if st.button("오늘 요일 파싱 결과 확인"):
            try:
                raw_sheet = fetch_sheet(SCHEDULE_URL, header=None)
                parsed_df, parse_errors = build_attendance_entries(date.today(), raw_sheet)

                st.write("파싱된 수업 개수:", len(parsed_df))
                st.dataframe(parsed_df.head(30), use_container_width=True)

                if parse_errors:
                    st.warning(f"파싱 실패 {len(parse_errors)}건")
                    st.write(parse_errors[:20])
                else:
                    st.success("파싱 실패 없음")

            except Exception as e:
                st.error(f"파싱 확인 실패: {e}")

        if st.button("신상카드 시트 구조 확인"):
            try:
                df1, df2 = fetch_profile_sheets()

                st.write("기존 신상카드 컬럼:", df1.columns.tolist())
                st.dataframe(df1.head(5), use_container_width=True)

                st.write("신규 신상카드 컬럼:", df2.columns.tolist())
                st.dataframe(df2.head(5), use_container_width=True)

            except Exception as e:
                st.error(f"신상카드 진단 실패: {e}")

        if st.button("캐시 새로고침"):
            st.cache_data.clear()
            st.success("캐시를 비웠습니다.")

        if st.session_state["last_parse_errors"]:
            st.subheader("최근 동기화 파싱 실패 내역")
            st.write(st.session_state["last_parse_errors"][:30])

    with tab3:
        st.subheader("사용자 목록")
        st.dataframe(st.session_state.users, use_container_width=True)
