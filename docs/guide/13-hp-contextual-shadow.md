# Hai Phong contextual models — shadow mode

Bundle `hp-contextual-v1-shadow` da duoc tao cho:

- DO: ExtraTrees voi `NH3, pH, Temperature, TSS`.
- Salinity: ExtraTrees voi cac feature tren va `month`.

Bundle/manifest nam trong `core/models/`. Pipeline tra payload
`contextual_models`, nhung khong ghi de sensor, khong doi suitability va khong
duoc alert engine su dung.

Gate bat buoc: `NH4_CONVERSION_CONFIRMED=true`, feature day du/in-range va nam
trong feature bounds training. Neu khong dat, payload tra `disabled` hoac
`rejected` kem ly do; khong fallback ngam thanh prediction.

Trang thai hien tai: **shadow disabled** theo mac dinh vi don vi/co so quy doi
NH4 -> NH3 chua duoc xac nhan. Chi sau khi xac nhan moi bat env flag va quan sat
prediction/OOD trong shadow mode; van khong duoc dung cho Emergency.
