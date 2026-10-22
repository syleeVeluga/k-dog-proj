"""The delivered Festival form's wording/labels, without participant responses."""

import json
import re

from .domain.catalog_v4 import RESOURCES


PROFILE = json.loads((RESOURCES / "mappings/forms-festival-20261022.json").read_bytes())


def participant_values(mapped):
    """Adapt explicitly mapped Festival fields; the original row remains immutable."""
    values = mapped.copy()
    for key, replacements in {
        "dog_sex": {"암컷": "암", "수컷": "수"},
        "dog_size": {"소형견": "소형", "중형견": "중형", "대형견": "대형"},
        "adoption_route": {"가정분양": "분양", "입양(보호소 등)": "입양"},
    }.items():
        if isinstance(values.get(key), str):
            raw = values[key].strip()
            values[key] = replacements.get(raw, raw)
    raw = values.get("dog_age_years")
    if isinstance(raw, str) and raw.strip():
        age = re.fullmatch(r"\s*(\d+)\s*(?:살|세|년)(?:\s*(\d+)\s*개월)?\s*", raw)
        months = re.fullmatch(r"\s*(\d+)\s*개월\s*", raw)
        if age:
            if age[2] is not None and int(age[2]) >= 12:
                raise ValueError("dog_age_years: 개월 부분은 0~11로 적으세요.")
            values["dog_age_years"] = int(age[1])
        elif months:
            values["dog_age_years"] = int(months[1]) // 12
        # Plain numbers keep the standard integer validation; ambiguous text is rejected.
    return values
