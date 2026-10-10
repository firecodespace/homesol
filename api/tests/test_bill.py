from homesol import bill


def test_bimonthly_bill_is_scaled_to_a_month():
    reading = bill.to_monthly({"units_consumed": 612, "bill_amount": 4830, "billing_days": 61, "distributor": "BESCOM"})
    assert reading.units_per_month == 301
    assert reading.bill_per_month == 2375
    assert reading.discom_id == "bescom"


def test_printed_history_is_averaged_in_preference_to_one_month():
    reading = bill.to_monthly({"units_consumed": 480, "bill_amount": 4100, "monthly_history": [480, 300, 240, 180]})
    # The printed months and this bill together: (480 + 480 + 300 + 240 + 180) / 5.
    assert reading.units_per_month == 336
    assert "5 months" in reading.basis
    # The amount keeps this bill's price per unit: 4100 / 480 x 336.
    assert reading.bill_per_month == 2870


def test_distributor_is_matched_by_name_then_by_state():
    assert bill.match_distributor("Maharashtra State Electricity Distribution Co. Ltd.", None) == "msedcl"
    assert bill.match_distributor("BSES Rajdhani Power Limited", "Delhi") == "delhi"
    assert bill.match_distributor(None, "Karnataka") == "bescom"
    # A named distributor we do not cover must not be guessed from its state.
    assert bill.match_distributor("Adani Electricity Mumbai", "Maharashtra") is None


def test_unreadable_fields_stay_empty():
    reading = bill.to_monthly({"distributor": "Torrent Power"})
    assert reading.units_per_month is None and reading.bill_per_month is None and reading.discom_id is None
