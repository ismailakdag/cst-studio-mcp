# Betik dizini

Bakımı yapılan sunucu `src/cst_mcp`, otomatik ve CST gerektirmeyen testler `tests` altındadır. Bu klasördeki önceki deney betikleri ana test paketiyle karıştırılmamalıdır.

| Grup | Dosyalar | Kullanım |
|---|---|---|
| Belge üretimi | `build_docs.py` | Kayıtlı araçlardan EN/TR rehberi, JSON katalog ve README tabloları üretir. CST'ye bağlanmaz. |
| Port yardımcıları | `port_tools.py`, `verify_port_patch.py` | Önce kaynak ve argümanlar incelenir; port/VBA geliştirme geçmişi. |
| Bağlantı ve sonuç inceleme geçmişi | `_ff_*.py`, `_mon_help.py`, `_reopen_tree.py`, `_tree_dump.py` | Yerel CST sonuçları ve kurulumuna bağlı tanı denemeleri. Genel istemci kurulum testi değildir. |
| CST ile uçtan uca deneyler | `run_patch_e2e.py`, `farfield_fix_e2e.py`, `postprocess_e2e.py`, `retry_full_flow.py` | Gerçek projeler açabilir veya solver çalıştırabilir. Canlı başka çalışma varken topluca çalıştırılmaz. |
| Anten tasarım denemeleri | `fractal_*.py`, `rfid_cp_*.py`, `run_patch_2p4.py`, `uhf_867_high_gain.py` | Önceki tasarım/optimizasyon işleri; güncel araştırma sonucu veya desteklenen sunucu giriş noktası sayılmaz. |

Yerel yollara ve CST sürümüne bağlı bu betikler korunmuştur. Bakım amacıyla dosya taşınmadı veya silinmedi. Sunucu kurulumu için [ana README](../README.md), güvenilirlik regresyonları için `python -m pytest` kullanılır. Testler gerçek CST'ye bağlanmaz; bu nedenle geçmeleri bütün CST araçlarının canlı doğrulandığı anlamına gelmez.
