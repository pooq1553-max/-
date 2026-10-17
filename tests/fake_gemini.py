"""테스트 전용 가짜 Gemini. SHORTS_FAKE_GEMINI=1 일 때만 extract_facts.py 가 사용한다.

실제 AI 가 아니다. 설명글에서 아래 표의 낱말을 찾아 '그 낱말이 들어 있는 문장'을 근거로 돌려줄 뿐이다.
표에 없는 항목이나 설명글에 없는 낱말은 빈칸으로 돌려준다 → 결과는 '확인 필요'.
"""
import json
import re

KNOWN = {
    "가게명": ["바다국밥"],
    "메뉴명": ["돼지국밥"],
    "가격": ["9,000원"],
    "지역": ["부산 해운대구 중동"],
    "특징": ["부추를 무한으로 리필"],
}


def ask(prompt):
    field_block = prompt.split("[항목]\n", 1)[1].split("\n\n[설명글]\n", 1)[0]
    fields = re.findall(r"^- (.+)$", field_block, flags=re.M)
    description = prompt.split("\n\n[설명글]\n", 1)[1]
    sentences = re.split(r"(?<=[.!?])\s+|\n", description)
    items = []
    for field in fields:
        value = evidence = ""
        for word in KNOWN.get(field, []):
            hit = next((s.strip() for s in sentences if word in s), "")
            if hit:
                value, evidence = word, hit
                break
        items.append({"field": field, "value": value, "evidence": evidence})
    return json.loads(json.dumps({"items": items}))
