"""seed_knowledge — the FAQ/RAG corpus (Agent 9, Phase 1).

~15 articles covering what patients actually ask a front desk after hours:
hours, locations, insurance, prep instructions, billing, portal help. The
Phase 4 FAQ answerer is instructed to answer ONLY from these articles, so
they are written as complete, self-contained answers.

Also refreshes each article's search_vector (title weighted A, body B) —
Postgres full-text IS the retrieval layer (FR-A5).

Idempotent: keyed on title; reruns update in place.
"""

from django.contrib.postgres.search import SearchVector
from django.core.management.base import BaseCommand

from frontdesk.models import KnowledgeArticle

ARTICLES = [
    {"title": "Clinic hours",
     "tags": ["hours"],
     "body": ("MediAssist Clinic is open Monday to Saturday, 9:00 AM to 8:00 PM. "
              "We are closed on Sundays and public holidays. The chat assistant is "
              "available 24x7 and can book appointments, take refill requests, and "
              "answer questions at any hour; anything needing a staff member is "
              "queued for the next working morning.")},
    {"title": "Clinic locations and parking",
     "tags": ["locations", "parking"],
     "body": ("Our main clinic is at 14 Karve Road, Kothrud, Pune 411038, with a "
              "second branch at 2 North Main Road, Koregaon Park, Pune 411001. Both "
              "locations have free patient parking; the Kothrud site's entrance is "
              "wheelchair accessible from the ground-floor lobby.")},
    {"title": "Emergency guidance",
     "tags": ["emergency"],
     "body": ("This clinic does not provide emergency care. If you have chest pain, "
              "difficulty breathing, signs of a stroke, severe bleeding, or any "
              "life-threatening symptoms, call 108 (ambulance) or go to the nearest "
              "emergency department immediately. Do not wait for a chat reply.")},
    {"title": "Accepted insurance providers",
     "tags": ["insurance"],
     "body": ("We currently accept BlueShield (Premium PPO and Basic HMO), Star "
              "Health, Apollo Munich, and HDFC Ergo. Cashless claims are available "
              "for BlueShield and Star Health; other insurers work on a "
              "reimbursement basis. Bring your policy card and a photo ID to your "
              "first visit.")},
    {"title": "What to bring to your first appointment",
     "tags": ["registration", "first-visit"],
     "body": ("Please bring a government photo ID, your insurance policy card if "
              "insured, a list of medications you currently take, and any recent "
              "lab reports or discharge summaries. Arriving 15 minutes early helps "
              "complete registration; you can also pre-register through this chat.")},
    {"title": "Fasting blood test preparation",
     "tags": ["prep", "labs"],
     "body": ("For fasting blood tests (glucose, lipid panel), do not eat or drink "
              "anything except plain water for 10 to 12 hours before your sample. "
              "Morning slots are recommended. Take your regular medications with "
              "water unless your doctor told you otherwise. Diabetics should ask "
              "their doctor about holding morning insulin until after the draw.")},
    {"title": "Blood pressure check preparation",
     "tags": ["prep", "vitals"],
     "body": ("Avoid caffeine, smoking, and exercise for 30 minutes before a blood "
              "pressure check. Sit quietly for five minutes beforehand. Wear a "
              "short-sleeved or loose-sleeved top so the cuff fits on your bare arm.")},
    {"title": "Vaccination clinic details",
     "tags": ["vaccination", "flu"],
     "body": ("Flu shots and routine adult vaccinations are given Monday to "
              "Saturday, 10:00 AM to 6:00 PM, at both locations — no separate "
              "appointment needed if you already have a visit booked, or book a "
              "10-minute vaccination slot through this chat. Stay 15 minutes for "
              "observation after any vaccine.")},
    {"title": "Prescription refills — how they work",
     "tags": ["refills", "pharmacy"],
     "body": ("You can request a refill through this chat any time. Refills are "
              "checked against your prescription (refills remaining, expiry, any "
              "required labs or follow-up) and sent to your doctor for approval, "
              "then to your preferred pharmacy. Allow one working day. Controlled "
              "substances can never be refilled automatically — those always need "
              "a doctor's review and may require a visit.")},
    {"title": "Billing and payment options",
     "tags": ["billing", "payments"],
     "body": ("We accept cash, all major cards, and UPI at the front desk. "
              "Itemized bills are emailed after every visit. For insured visits, "
              "your share (co-pay or deductible) is collected at checkout. Billing "
              "disputes or refund requests are handled by our accounts team on "
              "working days — this chat can raise a ticket for them.")},
    {"title": "Consultation fees",
     "tags": ["billing", "fees"],
     "body": ("A standard general-medicine consultation is Rs. 800. Specialist "
              "consultations range from Rs. 1,200 to Rs. 2,000 depending on the "
              "specialty. Follow-up visits within 14 days of a consultation are "
              "half price. Vaccination administration is Rs. 200 plus the vaccine "
              "cost.")},
    {"title": "Cancelling or rescheduling an appointment",
     "tags": ["appointments", "cancellation"],
     "body": ("You can cancel or reschedule through this chat up to 2 hours before "
              "your slot at no charge. Missed appointments without cancellation "
              "are recorded; after repeated no-shows the clinic may ask for "
              "pre-payment to book. Freed slots are offered automatically to "
              "waitlisted patients.")},
    {"title": "Getting your lab results",
     "tags": ["labs", "results"],
     "body": ("Most lab results are ready within 24 to 48 hours. You will get an "
              "SMS/email when they are uploaded to your record. Your doctor "
              "reviews every abnormal result; if anything needs action, the "
              "clinic contacts you directly. This chat can tell you whether a "
              "result has arrived, but interpreting results happens with your "
              "doctor.")},
    {"title": "Referrals to specialists",
     "tags": ["referrals"],
     "body": ("If your doctor refers you to a specialist, our referral team books "
              "the specialist visit, shares your records with consent, and tracks "
              "the appointment so nothing falls through. You can check your "
              "referral status any time through this chat. Insurance "
              "pre-authorization, when needed, is handled before the visit.")},
    {"title": "Patient portal and chat assistant help",
     "tags": ["portal", "chat"],
     "body": ("The chat assistant can register you, book/cancel appointments, "
              "request refills, check referral and authorization status, and "
              "answer clinic questions 24x7. For anything involving your medical "
              "record it will first verify your identity with your date of birth "
              "and a one-time code sent to your phone. It never shares medical "
              "information before that check.")},
    {"title": "Medical records and privacy",
     "tags": ["privacy", "records"],
     "body": ("Your records are shared only with your treating clinicians and, "
              "with your consent, with specialists you are referred to. To get a "
              "copy of your records, request it through this chat or at the front "
              "desk with photo ID; copies are prepared within three working days. "
              "Every access to your record is logged.")},
]


class Command(BaseCommand):
    help = "Seed the front-desk knowledge base (idempotent — keyed on title)."

    def handle(self, *args, **options):
        created = 0
        for spec in ARTICLES:
            _, was_created = KnowledgeArticle.objects.update_or_create(
                title=spec["title"],
                defaults={"body": spec["body"], "tags": spec["tags"]},
            )
            created += was_created
            self.stdout.write(f"{'created' if was_created else 'updated'}: {spec['title']}")

        # Refresh full-text vectors in one UPDATE — title outranks body.
        KnowledgeArticle.objects.update(
            search_vector=SearchVector("title", weight="A") + SearchVector("body", weight="B"),
        )
        self.stdout.write(self.style.SUCCESS(
            f"seeded {len(ARTICLES)} knowledge articles ({created} new), search vectors refreshed"))
