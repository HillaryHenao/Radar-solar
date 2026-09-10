from datetime import date

from scripts.build_data import batch_del_dia


def test_batch_del_dia_replica_la_convencion_existente():
    # La BD ya tiene sept1, sept9, sept10: mes abreviado + dia sin cero.
    assert batch_del_dia(date(2026, 9, 10)) == "sept10"
    assert batch_del_dia(date(2026, 9, 1)) == "sept1"


def test_batch_del_dia_generaliza_a_otros_meses():
    assert batch_del_dia(date(2026, 10, 5)) == "oct5"
    assert batch_del_dia(date(2027, 1, 20)) == "ene20"
