"""match_medication — common phrasings resolve to the right prescription or
None (a clarifying question). NEVER a wrong-medication match (Phase 4 exit).
Pure code, no AI: the model only supplies the stated string."""

import datetime

import pytest

from core.models import Doctor, Patient
from refills.services import match_medication
from refills.tests.test_eligibility import make_rx


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        dob=datetime.date(1990, 5, 17),
    )


@pytest.fixture
def doctor(db):
    return Doctor.objects.create(name="Dr. Asha Mehta", specialty="General Medicine")


class TestResolvesToTheRightPrescription:
    @pytest.mark.parametrize("stated", [
        "Amlodipine",                       # exact
        "amlodipine 5mg",                   # with dose
        "amlodipin",                        # misspelling
        "amlodapine",                       # worse misspelling
        "Norvasc",                          # brand name for the generic
        "I need my blood pressure meds",    # therapeutic class, single match
        "bp tablets please",                # class alias
    ])
    def test_common_phrasings(self, patient, doctor, stated):
        amlodipine = make_rx(patient, doctor)  # Amlodipine 5 mg
        make_rx(patient, doctor, medication_name="Metformin")  # a distractor
        assert match_medication(stated, patient) == amlodipine

    def test_brand_name_resolves_across_the_table(self, patient, doctor):
        lipitor = make_rx(patient, doctor, medication_name="Atorvastatin")
        assert match_medication("lipitor refill please", patient) == lipitor

    def test_thyroid_class(self, patient, doctor):
        synthroid = make_rx(patient, doctor, medication_name="Levothyroxine")
        assert match_medication("my thyroid medication", patient) == synthroid

    def test_renewal_duplicate_rows_resolve_to_the_newest(self, patient, doctor):
        # After an approval write-back the same medication exists twice;
        # that is not ambiguity — the newest prescription wins.
        import datetime as dt
        old = make_rx(patient, doctor)
        new = make_rx(patient, doctor, prescribed_date=dt.date.today())
        assert match_medication("amlodipine", patient) == new


class TestNeverAWrongMatch:
    def test_ambiguous_class_returns_none(self, patient, doctor):
        # Two active blood-pressure medications: guessing either is unsafe.
        make_rx(patient, doctor)  # Amlodipine
        make_rx(patient, doctor, medication_name="Losartan")
        assert match_medication("my blood pressure meds", patient) is None

    def test_two_statins_and_a_vague_word_returns_none(self, patient, doctor):
        make_rx(patient, doctor, medication_name="Atorvastatin")
        make_rx(patient, doctor, medication_name="Rosuvastatin")
        assert match_medication("my statin", patient) is None

    def test_a_similar_but_different_drug_never_cross_matches(self, patient, doctor):
        # Patient has atorvastatin only, asks for rosuvastatin: these are
        # DIFFERENT drugs — fuzzy matching must not bridge them.
        make_rx(patient, doctor, medication_name="Atorvastatin")
        assert match_medication("rosuvastatin", patient) is None

    def test_unknown_medication_returns_none(self, patient, doctor):
        make_rx(patient, doctor)
        assert match_medication("the little blue pill", patient) is None

    def test_empty_and_none_input(self, patient, doctor):
        make_rx(patient, doctor)
        assert match_medication("", patient) is None
        assert match_medication(None, patient) is None

    def test_inactive_prescriptions_are_never_matched(self, patient, doctor):
        make_rx(patient, doctor, medication_name="Losartan", status="expired")
        assert match_medication("losartan", patient) is None

    def test_someone_elses_prescription_is_invisible(self, patient, doctor):
        other = Patient.objects.create(first_name="Meera", last_name="Iyer",
                                       contact_number="9111111111",
                                       dob=datetime.date(1985, 1, 1))
        make_rx(other, doctor)
        assert match_medication("amlodipine", patient) is None
