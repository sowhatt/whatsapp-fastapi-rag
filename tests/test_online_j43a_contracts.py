from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.domains.core.contracts.commands import (
    ReserveStock, ConfirmReservation, ReleaseReservation, ConsumeReservation,
    RecordSale, CancelSale, GetStockAvailability,
)


def envelope():
    return dict(merchant_id=1, source="online", source_id="order-1", idempotency_key=uuid4())


def test_reserve_fingerprint_is_order_independent_and_payload_sensitive():
    data = envelope()
    a = ReserveStock(**data, lines=({"product_id":2,"quantity":3},{"product_id":1,"quantity":2}))
    b = ReserveStock(**data, lines=tuple(reversed(a.lines)))
    assert a.fingerprint() == b.fingerprint()
    assert a.fingerprint() != ReserveStock(**data, lines=({"product_id":2,"quantity":4},)).fingerprint()
    assert a.fingerprint() != a.model_copy(update={"merchant_id":2}).fingerprint()


@pytest.mark.parametrize("lines", [[], [{"product_id":1,"quantity":0}], [{"product_id":1,"quantity":True}],
                                    [{"product_id":1,"quantity":1},{"product_id":1,"quantity":2}]])
def test_reserve_rejects_ambiguous_or_invalid_quantities(lines):
    with pytest.raises(ValidationError):
        ReserveStock(**envelope(), lines=lines)


def test_all_seven_wire_contracts_roundtrip_and_reject_extra_fields():
    base=envelope(); reserved=dict(**base,reservation_set_id=uuid4(),expected_version=0)
    commands=[ReserveStock(**base,lines=({"product_id":1,"quantity":2},)),
              ConfirmReservation(**reserved),ReleaseReservation(**reserved,reason="cancelled"),
              ConsumeReservation(**reserved), RecordSale(**reserved,currency="XOF",total_minor=200),
              CancelSale(**base,sale_id=uuid4(),expected_version=1,reason="customer"),
              GetStockAvailability(merchant_id=1,product_ids=(1,2))]
    for command in commands:
        assert type(command).model_validate_json(command.model_dump_json()) == command
        with pytest.raises(ValidationError):
            type(command).model_validate({**command.model_dump(),"bypass_rls":True})
