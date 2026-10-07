"""
Species registry for aquaculture suitability classification.
Each species has its own thresholds, importance ranks, and parameter set.
"""

SPECIES = {
    'oyster': {
        'id': 'oyster',
        'name_vi': 'Con Hàu',
        'name_en': 'Oyster',
        'thresholds_file': 'oyster_thresholds.json',
        'model_file': 'oyster_model.pkl',
        'meta_file': 'oyster_meta.pkl',
        'label_thresholds': (0.60, 0.72),
    },
    'sonneratia': {
        'id': 'sonneratia',
        'name_vi': 'Cây Bần Chua',
        'name_en': 'Sonneratia Caseolaris',
        'thresholds_file': 'sonneratia_thresholds.json',
        'model_file': 'sonneratia_model.pkl',
        'meta_file': 'sonneratia_meta.pkl',
        'label_thresholds': (0.60, 0.72),
    },
    'cobia': {
        'id': 'cobia',
        'name_vi': 'Cá Giò',
        'name_en': 'Cobia',
        'thresholds_file': 'cobia_thresholds.json',
        'model_file': 'cobia_model.pkl',
        'meta_file': 'cobia_meta.pkl',
        'label_thresholds': (0.85, 0.90),
    },
}

DEFAULT_SPECIES = 'oyster'

# Loài mặc định cho từng vùng (Sonneratia tạm ẩn)
REGION_DEFAULT_SPECIES = {
    'quangninh': 'oyster',
    'haiphong':  'cobia',
}

# Loài hiển thị trong UI (ẩn Sonneratia cho đến khi có đủ dữ liệu)
_ACTIVE_SPECIES = ['oyster', 'cobia']


def get_species_choices(region: str = None) -> dict:
    """Return dict {id: display_name} for UI dropdowns.

    Parameters
    ----------
    region : str, optional
        Nếu truyền vào, sắp xếp loài mặc định của vùng lên đầu.
    """
    choices = {k: SPECIES[k]['name_vi'] for k in _ACTIVE_SPECIES}
    if region and region in REGION_DEFAULT_SPECIES:
        default = REGION_DEFAULT_SPECIES[region]
        # Đưa loài mặc định lên đầu dict
        ordered = {default: choices[default]}
        ordered.update({k: v for k, v in choices.items() if k != default})
        return ordered
    return choices


def get_default_species(region: str = None) -> str:
    """Trả về species id mặc định cho vùng, hoặc DEFAULT_SPECIES."""
    if region and region in REGION_DEFAULT_SPECIES:
        return REGION_DEFAULT_SPECIES[region]
    return DEFAULT_SPECIES
