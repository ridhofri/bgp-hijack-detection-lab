# Lab Notes

## 2026-09-21 — Sesi 1: Baseline 3 AS (victim 65010, transit 65001, user 65020)
- Deploy OK: 3 node FRR 10.7.1, binds read-only; file repo tetap UID 1000.
- Resource: ~200 MiB total untuk 3 router (~65 MiB/router), available 4.2 -> 4.0 GiB.
- Control plane: semua sesi Established, Notifications 0/0.
- User melihat 203.0.113.0/24 dengan AS_PATH "65001 65010" (origin = 65010).
- Data plane: ping user->victim 0% loss, TTL 63 (= 1 hop), RTT ~0.1 ms.
- Terbukti: /24 di loopback membuat seluruh blok lokal (203.0.113.99 membalas).
- Catatan validitas: RTT lab tidak realistis -> pertimbangkan tc netem untuk metrik waktu.
- Eksperimen ebgp-requires-policy: [ISI HASIL 10b: prediksi vs kenyataan]
