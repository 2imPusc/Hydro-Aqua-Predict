/**
 * One-line summaries of the evidence docs referenced by `config/alert_tiers.default.json`
 * (written from docs/eval/2026-10-23-*.md and docs/guide/27). Theory only, not field-validated.
 * Paths not listed here are shown without a summary.
 */
export const EVIDENCE_SUMMARY: Record<string, string> = {
  'docs/eval/2026-10-23-storm-damage.md':
    '22 ca bão có nguồn (16 cơn): giữ mốc cấp 6 và 8; P(hư hại lớn) = 0,5 quanh cấp 9 (gió là cận dưới) nên chưa chứng minh cấp 10 quá cao; cấp 12 giữ để khớp QĐ 18/2021.',
  'docs/guide/27-hazard-advisory-theory.md':
    'Khung cảnh báo bão và nắng nóng theo lý thuyết + dữ liệu công khai cho NB1; hồi cứu, shadow, không gửi người nuôi.',
  'docs/eval/2026-10-23-site-exposure.md':
    'Sóng tính theo đà gió (SPM 1984), chưa có số đo tại lồng; 1 m là tiêu chí chọn vị trí lồng nổi của NACA/FAO 1989, không phải giới hạn chịu tải.',
  'docs/eval/2026-10-23-storm-basin.md':
    'Ensemble quỹ đạo ECMWF ở ngưỡng 0,3 báo trước trung vị ~93 h nhưng chỉ 7 cơn (2024–2026) — mẫu nhỏ.',
  'docs/eval/2026-10-23-heat-skill.md':
    '130 ngày cảm biến: 31 ngày trung bình ≥ 31 °C, không ngày nào ≥ 33 °C — bậc 2–3 chưa từng xảy ra trong dữ liệu đo.',
  'docs/eval/2026-10-23-disease-risk.md':
    'Chỉ số không hơn khí hậu (3/5 sự kiện, kỳ vọng 3,3), chỉ 2 ca có tác nhân bệnh → chưa đủ bằng chứng; cơ chế rét kéo dài (Nhu et al. 2011) bị OISST bỏ sót (2008, 2016).',
  'docs/eval/2026-10-23-stocking-calendar.md':
    'Lạnh nặng < 18 °C theo cobia_thresholds; mốc < 20 °C là giả định của nhóm; lịch thả là rủi ro kỳ vọng từ khí hậu, không có ground truth.',
}
