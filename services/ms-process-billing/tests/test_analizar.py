import importlib.util
import json
import pathlib

spec = importlib.util.spec_from_file_location("analizar", pathlib.Path(__file__).parent.parent / "tools" / "analizar_sobrecosto.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_percentiles_y_prefijo(tmp_path, capsys):
    lines = []
    for i in range(1, 101):
        rec = {"message": "mensaje procesado", "timestamp": f"2026-10-11T10:00:{i % 60:02d}Z", "claimMs": float(i), "delayMs": 2000.0, "sqsMs": 10.0,
               "updateMs": 5.0, "commitMs": 3.0, "pollMs": 1.0, "handleMs": 2020.0, "totalMs": 2023.0, "sobrecostoMs": 23.0}
        lines.append(f"[pod/pb-{i % 2}/ms-process-billing] " + json.dumps(rec))
    lines.append("ruido que no es json")
    f = tmp_path / "l.txt"
    f.write_text("\n".join(lines))
    assert mod.main([str(f), "--por-pod"]) == 0
    out = capsys.readouterr().out
    assert "Mensajes analizados: 100  pods: 2" in out and "claimMs" in out and "pb-0" in out
    assert abs(mod.percentile(sorted(float(i) for i in range(1, 101)), .5) - 50.5) < 1e-9
