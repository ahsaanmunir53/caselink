import pytest

from app.extract.rules import agency_core, extract, iban_valid, mask


@pytest.mark.parametrize("raw", ["0300-1234867", "+92 300 1234867", "923001234867", "0300 1234867", "03001234867"])
def test_phone_formats_become_one_value(raw):
    found = [e for e in extract(f"call {raw} now").entities if e.kind == "phone"]
    assert [e.value for e in found] == ["+923001234867"]


def test_wallet_role_iban_checksum_and_masking():
    ex = extract("Send fee to JazzCash 0301-2345671 or account PK36 SCBL 0000 0011 2345 6702 and PK36SCBL0000001123456703")
    phones = [e for e in ex.entities if e.kind == "phone"]
    assert phones[0].role == "wallet"
    ibans = {e.value: e.valid for e in ex.entities if e.kind == "iban"}
    assert ibans == {"PK36SCBL0000001123456702": True, "PK36SCBL0000001123456703": False}
    assert iban_valid("PK36SCBL0000001123456702")
    assert mask("phone", "+923012345671") == "0301-***-5671"
    assert mask("iban", "PK36SCBL0000001123456702") == "PK36SCBL **** 6702"


def test_websites_are_found_even_when_disguised_and_official_ones_are_marked():
    ex = extract("Apply at hxxps://alnoor-overseas[.]com/apply. I checked beoe.gov.pk and complaint.fia.gov.pk. "
                 "Mail hr@lioncity-careers.com")
    domains = {e.value: e.official for e in ex.entities if e.kind == "domain"}
    assert domains == {"alnoor-overseas.com": False, "beoe.gov.pk": True, "fia.gov.pk": True}
    assert [e.value for e in ex.entities if e.kind == "email"] == ["hr@lioncity-careers.com"]


def test_helplines_are_official_and_never_link():
    ex = extract("I called the HBL helpline 111-111-425 and BEOE helpline 051-9201059.")
    assert all(e.official for e in ex.entities if e.kind == "phone")


def test_licence_handle_and_amount():
    ex = extract("They showed licence OEP-2214/RWP. Admin @Profit_Tasks_Admin. I paid Rs. 150,000 and PKR 2,000.")
    assert ("license", "OEP-2214/RWP") in {(e.kind, e.value) for e in ex.entities}
    assert ("handle", "@profit_tasks_admin") in {(e.kind, e.value) for e in ex.entities}
    assert ex.amount == 150000


@pytest.mark.parametrize(("name", "core"), [
    ("Al-Noor Overseas Employment Promoters", "alnoor"), ("Al Noor Overseas", "alnoor"), ("AlNoor Manpower", "alnoor"),
    ("Euro Work Permit Consultants", "euroworkpermit"), ("Lion City Placements", "lioncity"), ("ProfitTasks VIP", "profittasks"),
])
def test_agency_names_reduce_to_the_same_core(name, core):
    assert agency_core(name) == core
    assert core in {e.value for e in extract(f"Complaint against {name}. They took money.").entities if e.kind == "agency"}
