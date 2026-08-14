"""
Synthetic benchmark fixture generator.

Creates evaluation scenarios for local model selection. All scenarios are
synthetic — no real user data is used. Fixtures are version-controlled so
results are reproducible across machines and model versions.

Scenario types (minimum 10 per category):
  - Legal: case research, motion drafting, client correspondence, document review
  - Accounting: tax research, audit review, financial analysis, client communication
  - Consulting: report drafting, spreadsheet analysis, presentation preparation
  - Software development: code review, documentation, testing

Run:
  python benchmarks/generate_fixtures.py
  → writes benchmarks/fixtures/episodes.json
     and  benchmarks/fixtures/boundary_scenarios.json
"""
import json
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURES_DIR.mkdir(exist_ok=True)


# ── Synthetic episode scenarios ───────────────────────────────────────────────

EPISODES: list[dict] = [
    # ── Legal ──────────────────────────────────────────────────────────────────
    {
        "id": "legal-001",
        "category": "legal",
        "subcategory": "case_research",
        "episode_name": "Smith v. Johnson — Discovery Research",
        "started_at": "2026-01-15T09:00:00Z",
        "ended_at": "2026-01-15T10:30:00Z",
        "duration_minutes": 90.0,
        "observations": [
            {"timestamp": "09:00", "app": "Google Chrome", "window_title": "Westlaw — Search Results", "entities": ["Smith v. Johnson", "Case No. 2024-CV-1234"]},
            {"timestamp": "09:15", "app": "Google Chrome", "window_title": "Johnson v. Smith (2019) — Westlaw", "entities": ["Case No. 2019-CV-789"]},
            {"timestamp": "09:35", "app": "Microsoft Word", "window_title": "Discovery Memo — Smith Matter.docx", "entities": ["Smith v. Johnson"]},
            {"timestamp": "09:55", "app": "Google Chrome", "window_title": "PACER — Docket 2024-CV-1234", "entities": ["2024-CV-1234"]},
            {"timestamp": "10:15", "app": "Microsoft Word", "window_title": "Discovery Memo — Smith Matter.docx", "entities": ["Smith v. Johnson"]},
        ],
        "ground_truth_activity": "research",
        "ground_truth_observations": [
            {"timestamp": "09:00", "text": "Researched precedents on Westlaw for Smith v. Johnson discovery issues"},
            {"timestamp": "09:35", "text": "Drafted discovery memo summarizing relevant case law"},
            {"timestamp": "09:55", "text": "Reviewed PACER docket for case 2024-CV-1234"},
            {"timestamp": "10:15", "text": "Continued drafting discovery memo"},
        ],
    },
    {
        "id": "legal-002",
        "category": "legal",
        "subcategory": "motion_drafting",
        "episode_name": "Martinez Estate — Motion to Dismiss",
        "started_at": "2026-01-15T11:00:00Z",
        "ended_at": "2026-01-15T12:45:00Z",
        "duration_minutes": 105.0,
        "observations": [
            {"timestamp": "11:00", "app": "Microsoft Word", "window_title": "Motion to Dismiss — Martinez Estate.docx", "entities": ["Martinez Estate", "Claim #2024-E-4521"]},
            {"timestamp": "11:20", "app": "Adobe Acrobat", "window_title": "Martinez_Estate_Complaint.pdf", "entities": ["Martinez Estate"]},
            {"timestamp": "11:45", "app": "Microsoft Word", "window_title": "Motion to Dismiss — Martinez Estate.docx", "entities": ["Martinez Estate"]},
            {"timestamp": "12:10", "app": "Google Chrome", "window_title": "FRCP Rule 12(b)(6) — Cornell LII", "entities": []},
            {"timestamp": "12:30", "app": "Microsoft Word", "window_title": "Motion to Dismiss — Martinez Estate.docx", "entities": ["Martinez Estate"]},
        ],
        "ground_truth_activity": "drafting",
        "ground_truth_observations": [
            {"timestamp": "11:00", "text": "Began drafting motion to dismiss for Martinez Estate matter"},
            {"timestamp": "11:20", "text": "Reviewed complaint in Martinez Estate PDF"},
            {"timestamp": "12:10", "text": "Checked FRCP Rule 12(b)(6) standards for motion to dismiss"},
            {"timestamp": "12:30", "text": "Continued drafting and refining motion to dismiss arguments"},
        ],
    },
    {
        "id": "legal-003",
        "category": "legal",
        "subcategory": "client_correspondence",
        "episode_name": "Chen v. Patel — Client Update Email",
        "started_at": "2026-01-15T14:00:00Z",
        "ended_at": "2026-01-15T14:45:00Z",
        "duration_minutes": 45.0,
        "observations": [
            {"timestamp": "14:00", "app": "Microsoft Outlook", "window_title": "RE: Chen v. Patel Settlement — Inbox", "entities": ["Chen v. Patel"]},
            {"timestamp": "14:15", "app": "Microsoft Outlook", "window_title": "New Email — To: chen@example.com", "entities": ["Chen v. Patel"]},
            {"timestamp": "14:30", "app": "Microsoft Word", "window_title": "Settlement Summary — Chen Matter.docx", "entities": ["Chen v. Patel", "Invoice #2024-789"]},
            {"timestamp": "14:40", "app": "Microsoft Outlook", "window_title": "RE: Chen v. Patel Settlement — Compose", "entities": ["Chen v. Patel"]},
        ],
        "ground_truth_activity": "correspondence",
        "ground_truth_observations": [
            {"timestamp": "14:00", "text": "Reviewed client email regarding Chen v. Patel settlement"},
            {"timestamp": "14:15", "text": "Composed client update email for Chen matter"},
            {"timestamp": "14:30", "text": "Referenced settlement summary document while drafting email"},
            {"timestamp": "14:40", "text": "Finalized and prepared to send client update on settlement status"},
        ],
    },
    {
        "id": "legal-004",
        "category": "legal",
        "subcategory": "document_review",
        "episode_name": "Williams Acquisition — Contract Review",
        "started_at": "2026-01-16T09:00:00Z",
        "ended_at": "2026-01-16T11:00:00Z",
        "duration_minutes": 120.0,
        "observations": [
            {"timestamp": "09:00", "app": "Adobe Acrobat", "window_title": "Williams_Acquisition_Agreement_v3.pdf", "entities": ["Williams Acquisition", "Matter #2024-M-0099"]},
            {"timestamp": "09:25", "app": "Microsoft Word", "window_title": "Contract Review Notes — Williams.docx", "entities": ["Williams Acquisition"]},
            {"timestamp": "09:50", "app": "Adobe Acrobat", "window_title": "Williams_Acquisition_Agreement_v3.pdf", "entities": ["Williams Acquisition"]},
            {"timestamp": "10:20", "app": "Microsoft Word", "window_title": "Contract Review Notes — Williams.docx", "entities": ["Williams Acquisition"]},
            {"timestamp": "10:45", "app": "Adobe Acrobat", "window_title": "Williams_Acquisition_Schedules.pdf", "entities": ["Williams Acquisition"]},
        ],
        "ground_truth_activity": "review",
        "ground_truth_observations": [
            {"timestamp": "09:00", "text": "Began reviewing Williams Acquisition Agreement v3"},
            {"timestamp": "09:25", "text": "Documented review notes and flagged issues"},
            {"timestamp": "09:50", "text": "Continued reviewing acquisition agreement"},
            {"timestamp": "10:45", "text": "Reviewed acquisition schedules and supporting documents"},
        ],
    },
    {
        "id": "legal-005",
        "category": "legal",
        "subcategory": "case_research",
        "episode_name": "Thompson IP — Patent Infringement Research",
        "started_at": "2026-01-16T13:00:00Z",
        "ended_at": "2026-01-16T14:30:00Z",
        "duration_minutes": 90.0,
        "observations": [
            {"timestamp": "13:00", "app": "Google Chrome", "window_title": "USPTO Patent Full-Text Database", "entities": ["Patent No. US9876543B2"]},
            {"timestamp": "13:20", "app": "Google Chrome", "window_title": "Google Scholar — patent infringement willful", "entities": []},
            {"timestamp": "13:45", "app": "Microsoft Word", "window_title": "IP Research Memo — Thompson.docx", "entities": ["Thompson IP", "Patent No. US9876543B2"]},
            {"timestamp": "14:10", "app": "Google Chrome", "window_title": "Westlaw — Patent Infringement Cases 2023-2025", "entities": []},
            {"timestamp": "14:25", "app": "Microsoft Word", "window_title": "IP Research Memo — Thompson.docx", "entities": ["Thompson IP"]},
        ],
        "ground_truth_activity": "research",
        "ground_truth_observations": [
            {"timestamp": "13:00", "text": "Researched patent US9876543B2 in USPTO database"},
            {"timestamp": "13:20", "text": "Researched patent infringement willfulness standards"},
            {"timestamp": "13:45", "text": "Drafted IP research memo for Thompson matter"},
            {"timestamp": "14:10", "text": "Reviewed recent patent infringement cases on Westlaw"},
        ],
    },
    {
        "id": "legal-006",
        "category": "legal",
        "subcategory": "document_review",
        "episode_name": "Harrison Divorce — Financial Disclosure Review",
        "started_at": "2026-01-17T10:00:00Z",
        "ended_at": "2026-01-17T11:30:00Z",
        "duration_minutes": 90.0,
        "observations": [
            {"timestamp": "10:00", "app": "Adobe Acrobat", "window_title": "Harrison_FL-142_Financial_Disclosure.pdf", "entities": ["Harrison"]},
            {"timestamp": "10:30", "app": "Microsoft Excel", "window_title": "Harrison Asset Analysis.xlsx", "entities": ["Harrison"]},
            {"timestamp": "11:00", "app": "Adobe Acrobat", "window_title": "Harrison_Bank_Statements_2023.pdf", "entities": ["Harrison"]},
            {"timestamp": "11:20", "app": "Microsoft Word", "window_title": "Financial Review Notes — Harrison.docx", "entities": ["Harrison"]},
        ],
        "ground_truth_activity": "review",
        "ground_truth_observations": [
            {"timestamp": "10:00", "text": "Reviewed FL-142 financial disclosure for Harrison divorce matter"},
            {"timestamp": "10:30", "text": "Analyzed asset values in Harrison Excel spreadsheet"},
            {"timestamp": "11:00", "text": "Reviewed 2023 bank statements for Harrison matter"},
            {"timestamp": "11:20", "text": "Documented financial review findings"},
        ],
    },
    {
        "id": "legal-007",
        "category": "legal",
        "subcategory": "motion_drafting",
        "episode_name": "Nguyen Custody — Reply Brief",
        "started_at": "2026-01-17T14:00:00Z",
        "ended_at": "2026-01-17T16:00:00Z",
        "duration_minutes": 120.0,
        "observations": [
            {"timestamp": "14:00", "app": "Microsoft Word", "window_title": "Reply Brief — Nguyen Custody.docx", "entities": ["Nguyen", "Case No. 2025-FAM-0341"]},
            {"timestamp": "14:30", "app": "Adobe Acrobat", "window_title": "Opposing_Counsel_Brief_Nguyen.pdf", "entities": ["Nguyen"]},
            {"timestamp": "15:00", "app": "Google Chrome", "window_title": "Best Interests of Child Standard — California Courts", "entities": []},
            {"timestamp": "15:30", "app": "Microsoft Word", "window_title": "Reply Brief — Nguyen Custody.docx", "entities": ["Nguyen"]},
            {"timestamp": "15:50", "app": "Microsoft Word", "window_title": "Reply Brief — Nguyen Custody.docx", "entities": ["Nguyen"]},
        ],
        "ground_truth_activity": "drafting",
        "ground_truth_observations": [
            {"timestamp": "14:00", "text": "Began drafting reply brief for Nguyen custody matter"},
            {"timestamp": "14:30", "text": "Reviewed opposing counsel's brief in Nguyen matter"},
            {"timestamp": "15:00", "text": "Researched best interests of child standard for California courts"},
            {"timestamp": "15:30", "text": "Continued drafting and refining reply brief arguments"},
        ],
    },
    {
        "id": "legal-008",
        "category": "legal",
        "subcategory": "client_correspondence",
        "episode_name": "Garcia Real Estate — Title Review Communication",
        "started_at": "2026-01-18T09:30:00Z",
        "ended_at": "2026-01-18T10:15:00Z",
        "duration_minutes": 45.0,
        "observations": [
            {"timestamp": "09:30", "app": "Microsoft Outlook", "window_title": "Garcia Real Estate — Title Commitment — Inbox", "entities": ["Garcia"]},
            {"timestamp": "09:45", "app": "Adobe Acrobat", "window_title": "Garcia_Title_Commitment.pdf", "entities": ["Garcia", "Property ID: 12345-A"]},
            {"timestamp": "10:00", "app": "Microsoft Outlook", "window_title": "RE: Garcia Real Estate Title Issues — Compose", "entities": ["Garcia"]},
        ],
        "ground_truth_activity": "correspondence",
        "ground_truth_observations": [
            {"timestamp": "09:30", "text": "Reviewed title commitment for Garcia real estate transaction"},
            {"timestamp": "09:45", "text": "Examined title commitment document for exceptions and issues"},
            {"timestamp": "10:00", "text": "Drafted response to client regarding title commitment issues"},
        ],
    },
    {
        "id": "legal-009",
        "category": "legal",
        "subcategory": "case_research",
        "episode_name": "Park Employment — Wrongful Termination Research",
        "started_at": "2026-01-18T13:00:00Z",
        "ended_at": "2026-01-18T14:15:00Z",
        "duration_minutes": 75.0,
        "observations": [
            {"timestamp": "13:00", "app": "Google Chrome", "window_title": "Westlaw — Wrongful Termination California FEHA", "entities": []},
            {"timestamp": "13:20", "app": "Google Chrome", "window_title": "DFEH v. Employer (2022) — Westlaw", "entities": []},
            {"timestamp": "13:45", "app": "Microsoft Word", "window_title": "Employment Law Research — Park Matter.docx", "entities": ["Park"]},
            {"timestamp": "14:05", "app": "Google Chrome", "window_title": "California Labor Code § 1102.5 — LexisNexis", "entities": []},
        ],
        "ground_truth_activity": "research",
        "ground_truth_observations": [
            {"timestamp": "13:00", "text": "Researched wrongful termination standards under California FEHA"},
            {"timestamp": "13:20", "text": "Reviewed DFEH v. Employer precedent case"},
            {"timestamp": "13:45", "text": "Drafted employment law research memo for Park matter"},
            {"timestamp": "14:05", "text": "Analyzed California Labor Code whistleblower protections"},
        ],
    },
    {
        "id": "legal-010",
        "category": "legal",
        "subcategory": "document_review",
        "episode_name": "Lee Commercial Lease — Tenant Obligations Review",
        "started_at": "2026-01-19T10:00:00Z",
        "ended_at": "2026-01-19T11:15:00Z",
        "duration_minutes": 75.0,
        "observations": [
            {"timestamp": "10:00", "app": "Adobe Acrobat", "window_title": "Lee_Commercial_Lease_Agreement.pdf", "entities": ["Lee", "Lease #CL-2024-0892"]},
            {"timestamp": "10:25", "app": "Microsoft Word", "window_title": "Lease Review Checklist — Lee.docx", "entities": ["Lee"]},
            {"timestamp": "10:50", "app": "Adobe Acrobat", "window_title": "Lee_Commercial_Lease_Agreement.pdf", "entities": ["Lee"]},
            {"timestamp": "11:10", "app": "Microsoft Word", "window_title": "Lease Review Checklist — Lee.docx", "entities": ["Lee"]},
        ],
        "ground_truth_activity": "review",
        "ground_truth_observations": [
            {"timestamp": "10:00", "text": "Began reviewing Lee commercial lease agreement"},
            {"timestamp": "10:25", "text": "Completed lease review checklist for tenant obligations"},
            {"timestamp": "10:50", "text": "Continued detailed review of lease provisions"},
            {"timestamp": "11:10", "text": "Finalized lease review notes and flagged key issues"},
        ],
    },

    # ── Accounting (10 scenarios) ──────────────────────────────────────────────
    {
        "id": "acct-001",
        "category": "accounting",
        "subcategory": "tax_research",
        "episode_name": "Roberts Family Trust — Section 199A Deduction",
        "started_at": "2026-02-01T09:00:00Z",
        "ended_at": "2026-02-01T10:30:00Z",
        "duration_minutes": 90.0,
        "observations": [
            {"timestamp": "09:00", "app": "Google Chrome", "window_title": "IRS.gov — Section 199A Qualified Business Income", "entities": []},
            {"timestamp": "09:20", "app": "CCH ProSystem", "window_title": "Roberts Family Trust — Tax Research", "entities": ["Roberts Family Trust"]},
            {"timestamp": "09:45", "app": "Microsoft Word", "window_title": "199A Analysis — Roberts Trust.docx", "entities": ["Roberts Family Trust"]},
            {"timestamp": "10:10", "app": "Google Chrome", "window_title": "Treasury Reg. § 1.199A-1 — Cornell LII", "entities": []},
            {"timestamp": "10:25", "app": "Microsoft Word", "window_title": "199A Analysis — Roberts Trust.docx", "entities": ["Roberts Family Trust"]},
        ],
        "ground_truth_activity": "research",
        "ground_truth_observations": [
            {"timestamp": "09:00", "text": "Researched Section 199A qualified business income deduction rules"},
            {"timestamp": "09:20", "text": "Applied research to Roberts Family Trust tax situation in CCH ProSystem"},
            {"timestamp": "09:45", "text": "Drafted Section 199A analysis memorandum for Roberts Trust"},
            {"timestamp": "10:10", "text": "Reviewed Treasury Regulation 1.199A-1 for trust-specific rules"},
        ],
    },
    {
        "id": "acct-002",
        "category": "accounting",
        "subcategory": "audit_review",
        "episode_name": "Apex Manufacturing — Q3 Inventory Audit",
        "started_at": "2026-02-01T11:00:00Z",
        "ended_at": "2026-02-01T12:30:00Z",
        "duration_minutes": 90.0,
        "observations": [
            {"timestamp": "11:00", "app": "Microsoft Excel", "window_title": "Apex_Q3_Inventory_Count.xlsx", "entities": ["Apex Manufacturing", "Invoice #INV-2024-4521"]},
            {"timestamp": "11:25", "app": "Adobe Acrobat", "window_title": "Apex_Warehouse_Physical_Count.pdf", "entities": ["Apex Manufacturing"]},
            {"timestamp": "11:50", "app": "Microsoft Excel", "window_title": "Apex_Q3_Inventory_Variance.xlsx", "entities": ["Apex Manufacturing"]},
            {"timestamp": "12:15", "app": "Microsoft Word", "window_title": "Inventory Audit Findings — Apex Q3.docx", "entities": ["Apex Manufacturing"]},
        ],
        "ground_truth_activity": "review",
        "ground_truth_observations": [
            {"timestamp": "11:00", "text": "Reviewed Q3 inventory count data for Apex Manufacturing audit"},
            {"timestamp": "11:25", "text": "Cross-referenced warehouse physical count with records"},
            {"timestamp": "11:50", "text": "Analyzed inventory variance for Q3"},
            {"timestamp": "12:15", "text": "Documented inventory audit findings"},
        ],
    },
    {
        "id": "acct-003",
        "category": "accounting",
        "subcategory": "financial_analysis",
        "episode_name": "Meridian Partners — Cash Flow Projection",
        "started_at": "2026-02-02T09:00:00Z",
        "ended_at": "2026-02-02T10:45:00Z",
        "duration_minutes": 105.0,
        "observations": [
            {"timestamp": "09:00", "app": "Microsoft Excel", "window_title": "Meridian_Cash_Flow_Model_2026.xlsx", "entities": ["Meridian Partners"]},
            {"timestamp": "09:30", "app": "Microsoft Excel", "window_title": "Meridian_Historical_Financials.xlsx", "entities": ["Meridian Partners"]},
            {"timestamp": "10:00", "app": "Microsoft Excel", "window_title": "Meridian_Cash_Flow_Model_2026.xlsx", "entities": ["Meridian Partners"]},
            {"timestamp": "10:30", "app": "Microsoft PowerPoint", "window_title": "Meridian Partners Financial Review.pptx", "entities": ["Meridian Partners"]},
        ],
        "ground_truth_activity": "analysis",
        "ground_truth_observations": [
            {"timestamp": "09:00", "text": "Built 2026 cash flow projection model for Meridian Partners"},
            {"timestamp": "09:30", "text": "Analyzed historical financial data for Meridian to inform projections"},
            {"timestamp": "10:00", "text": "Refined cash flow assumptions and scenarios"},
            {"timestamp": "10:30", "text": "Prepared financial review presentation for Meridian Partners"},
        ],
    },
    {
        "id": "acct-004",
        "category": "accounting",
        "subcategory": "client_communication",
        "episode_name": "Dixon Bakeries — Year-End Tax Planning",
        "started_at": "2026-02-02T14:00:00Z",
        "ended_at": "2026-02-02T15:00:00Z",
        "duration_minutes": 60.0,
        "observations": [
            {"timestamp": "14:00", "app": "Microsoft Outlook", "window_title": "Dixon Bakeries — Year-End Planning — Inbox", "entities": ["Dixon Bakeries"]},
            {"timestamp": "14:15", "app": "Microsoft Word", "window_title": "Dixon Year-End Tax Planning Letter.docx", "entities": ["Dixon Bakeries"]},
            {"timestamp": "14:40", "app": "CCH ProSystem", "window_title": "Dixon Bakeries — Tax Projection 2025", "entities": ["Dixon Bakeries"]},
            {"timestamp": "14:55", "app": "Microsoft Outlook", "window_title": "Dixon Bakeries — Year-End Planning — Compose", "entities": ["Dixon Bakeries"]},
        ],
        "ground_truth_activity": "correspondence",
        "ground_truth_observations": [
            {"timestamp": "14:00", "text": "Reviewed Dixon Bakeries year-end planning inquiry"},
            {"timestamp": "14:15", "text": "Drafted year-end tax planning letter for Dixon Bakeries"},
            {"timestamp": "14:40", "text": "Prepared 2025 tax projection in CCH ProSystem for Dixon"},
            {"timestamp": "14:55", "text": "Finalized and sent year-end planning communication to Dixon Bakeries"},
        ],
    },
    {
        "id": "acct-005",
        "category": "accounting",
        "subcategory": "tax_research",
        "episode_name": "Fernandez LLC — R&D Tax Credit Analysis",
        "started_at": "2026-02-03T10:00:00Z",
        "ended_at": "2026-02-03T11:30:00Z",
        "duration_minutes": 90.0,
        "observations": [
            {"timestamp": "10:00", "app": "Google Chrome", "window_title": "IRS Form 6765 — R&D Tax Credit", "entities": []},
            {"timestamp": "10:20", "app": "Google Chrome", "window_title": "IRC § 41 Research Credit — Tax Foundation", "entities": []},
            {"timestamp": "10:45", "app": "Microsoft Excel", "window_title": "Fernandez_RD_Credit_Calculation.xlsx", "entities": ["Fernandez LLC"]},
            {"timestamp": "11:10", "app": "Microsoft Word", "window_title": "R&D Credit Memo — Fernandez.docx", "entities": ["Fernandez LLC"]},
        ],
        "ground_truth_activity": "analysis",
        "ground_truth_observations": [
            {"timestamp": "10:00", "text": "Researched IRS Form 6765 R&D tax credit qualification criteria"},
            {"timestamp": "10:20", "text": "Analyzed IRC Section 41 research credit rules for Fernandez"},
            {"timestamp": "10:45", "text": "Calculated R&D tax credit for Fernandez LLC"},
            {"timestamp": "11:10", "text": "Documented R&D credit analysis and recommendations"},
        ],
    },
    {
        "id": "acct-006", "category": "accounting", "subcategory": "audit_review",
        "episode_name": "Sunrise Hotels — Revenue Recognition Audit",
        "started_at": "2026-02-03T13:00:00Z", "ended_at": "2026-02-03T14:30:00Z",
        "duration_minutes": 90.0,
        "observations": [
            {"timestamp": "13:00", "app": "Microsoft Excel", "window_title": "Sunrise_Revenue_Schedules_Q4.xlsx", "entities": ["Sunrise Hotels"]},
            {"timestamp": "13:30", "app": "Adobe Acrobat", "window_title": "Sunrise_Management_Contracts.pdf", "entities": ["Sunrise Hotels"]},
            {"timestamp": "14:00", "app": "Microsoft Word", "window_title": "Revenue Recognition Audit Notes — Sunrise.docx", "entities": ["Sunrise Hotels"]},
        ],
        "ground_truth_activity": "review",
        "ground_truth_observations": [
            {"timestamp": "13:00", "text": "Reviewed Q4 revenue schedules for Sunrise Hotels audit"},
            {"timestamp": "13:30", "text": "Examined management contracts for revenue recognition implications"},
            {"timestamp": "14:00", "text": "Documented revenue recognition audit findings for Sunrise Hotels"},
        ],
    },
    {
        "id": "acct-007", "category": "accounting", "subcategory": "financial_analysis",
        "episode_name": "Blackwood Capital — Investment Portfolio Analysis",
        "started_at": "2026-02-04T09:00:00Z", "ended_at": "2026-02-04T10:30:00Z",
        "duration_minutes": 90.0,
        "observations": [
            {"timestamp": "09:00", "app": "Bloomberg Terminal", "window_title": "Blackwood Portfolio Overview", "entities": ["Blackwood Capital"]},
            {"timestamp": "09:25", "app": "Microsoft Excel", "window_title": "Blackwood_Portfolio_Returns_2025.xlsx", "entities": ["Blackwood Capital"]},
            {"timestamp": "10:00", "app": "Microsoft Excel", "window_title": "Blackwood_Risk_Analysis.xlsx", "entities": ["Blackwood Capital"]},
            {"timestamp": "10:20", "app": "Microsoft PowerPoint", "window_title": "Blackwood Portfolio Review Q4 2025.pptx", "entities": ["Blackwood Capital"]},
        ],
        "ground_truth_activity": "analysis",
        "ground_truth_observations": [
            {"timestamp": "09:00", "text": "Reviewed Blackwood Capital portfolio overview in Bloomberg"},
            {"timestamp": "09:25", "text": "Analyzed 2025 portfolio returns for Blackwood Capital"},
            {"timestamp": "10:00", "text": "Conducted risk analysis for Blackwood portfolio"},
            {"timestamp": "10:20", "text": "Prepared Q4 portfolio review presentation"},
        ],
    },
    {
        "id": "acct-008", "category": "accounting", "subcategory": "client_communication",
        "episode_name": "Patel Restaurant Group — Sales Tax Compliance",
        "started_at": "2026-02-04T13:00:00Z", "ended_at": "2026-02-04T13:45:00Z",
        "duration_minutes": 45.0,
        "observations": [
            {"timestamp": "13:00", "app": "Microsoft Outlook", "window_title": "Patel Restaurant — Sales Tax Audit Notice — Inbox", "entities": ["Patel Restaurant Group"]},
            {"timestamp": "13:15", "app": "Microsoft Word", "window_title": "Sales Tax Response Letter — Patel.docx", "entities": ["Patel Restaurant Group"]},
            {"timestamp": "13:35", "app": "Microsoft Outlook", "window_title": "Patel Restaurant — Sales Tax Response — Compose", "entities": ["Patel Restaurant Group"]},
        ],
        "ground_truth_activity": "correspondence",
        "ground_truth_observations": [
            {"timestamp": "13:00", "text": "Reviewed sales tax audit notice for Patel Restaurant Group"},
            {"timestamp": "13:15", "text": "Drafted response letter to state revenue department for Patel"},
            {"timestamp": "13:35", "text": "Sent sales tax compliance response on behalf of Patel Restaurant"},
        ],
    },
    {
        "id": "acct-009", "category": "accounting", "subcategory": "tax_research",
        "episode_name": "O'Brien Construction — Contractor vs. Employee Classification",
        "started_at": "2026-02-05T10:00:00Z", "ended_at": "2026-02-05T11:15:00Z",
        "duration_minutes": 75.0,
        "observations": [
            {"timestamp": "10:00", "app": "Google Chrome", "window_title": "IRS 20-Factor Test — Independent Contractor", "entities": []},
            {"timestamp": "10:25", "app": "Google Chrome", "window_title": "California ABC Test — Worker Classification", "entities": []},
            {"timestamp": "10:50", "app": "Microsoft Word", "window_title": "Worker Classification Memo — O'Brien.docx", "entities": ["O'Brien Construction"]},
        ],
        "ground_truth_activity": "research",
        "ground_truth_observations": [
            {"timestamp": "10:00", "text": "Researched IRS 20-factor test for independent contractor classification"},
            {"timestamp": "10:25", "text": "Analyzed California ABC test requirements for O'Brien Construction workers"},
            {"timestamp": "10:50", "text": "Drafted worker classification analysis memo for O'Brien Construction"},
        ],
    },
    {
        "id": "acct-010", "category": "accounting", "subcategory": "audit_review",
        "episode_name": "TechStart Inc. — Stock-Based Compensation Review",
        "started_at": "2026-02-05T14:00:00Z", "ended_at": "2026-02-05T15:15:00Z",
        "duration_minutes": 75.0,
        "observations": [
            {"timestamp": "14:00", "app": "Microsoft Excel", "window_title": "TechStart_SBC_Schedule_2025.xlsx", "entities": ["TechStart Inc."]},
            {"timestamp": "14:30", "app": "Adobe Acrobat", "window_title": "TechStart_Option_Agreements.pdf", "entities": ["TechStart Inc."]},
            {"timestamp": "15:00", "app": "Microsoft Word", "window_title": "SBC Audit Workpapers — TechStart.docx", "entities": ["TechStart Inc."]},
        ],
        "ground_truth_activity": "review",
        "ground_truth_observations": [
            {"timestamp": "14:00", "text": "Reviewed stock-based compensation schedule for TechStart Inc."},
            {"timestamp": "14:30", "text": "Examined option agreements for ASC 718 compliance"},
            {"timestamp": "15:00", "text": "Prepared SBC audit workpapers for TechStart"},
        ],
    },
]


# ── Episode boundary scenarios ────────────────────────────────────────────────

BOUNDARY_SCENARIOS: list[dict] = [
    {
        "id": "boundary-001",
        "description": "Clear app switch from browser research to Word drafting",
        "current_episode": "Legal research for Smith matter",
        "before": {"app": "Google Chrome", "window_title": "Westlaw — Smith v. Johnson", "ocr_excerpt": "LEXISNEXIS WESTLAW CASE LAW"},
        "after": {"app": "Microsoft Word", "window_title": "Motion to Dismiss — Smith.docx", "ocr_excerpt": "IN THE SUPERIOR COURT"},
        "ground_truth_new_episode": False,
        "ground_truth_activity": "drafting",
        "rationale": "Same matter (Smith), different tool — continuation of same episode",
    },
    {
        "id": "boundary-002",
        "description": "Matter switch: Smith research → Martinez drafting",
        "current_episode": "Smith v. Johnson research",
        "before": {"app": "Google Chrome", "window_title": "Westlaw — Smith v. Johnson", "ocr_excerpt": "SMITH V JOHNSON DISCOVERY"},
        "after": {"app": "Microsoft Word", "window_title": "Motion to Dismiss — Martinez Estate.docx", "ocr_excerpt": "IN THE MATTER OF MARTINEZ ESTATE"},
        "ground_truth_new_episode": True,
        "ground_truth_activity": "drafting",
        "rationale": "Different matter name — new episode required",
    },
    {
        "id": "boundary-003",
        "description": "Email in middle of drafting session (same matter)",
        "current_episode": "Williams acquisition contract review",
        "before": {"app": "Adobe Acrobat", "window_title": "Williams_Agreement.pdf", "ocr_excerpt": "REPRESENTATIONS AND WARRANTIES"},
        "after": {"app": "Microsoft Outlook", "window_title": "RE: Williams Acquisition Timeline", "ocr_excerpt": "From: williams@example.com"},
        "ground_truth_new_episode": False,
        "ground_truth_activity": "correspondence",
        "rationale": "Email about same matter — continuation; activity type changes to correspondence",
    },
    {
        "id": "boundary-004",
        "description": "Personal email (unrelated to any matter)",
        "current_episode": "Smith v. Johnson discovery research",
        "before": {"app": "Google Chrome", "window_title": "Westlaw — Smith Discovery", "ocr_excerpt": "DISCOVERY RULE FRCP 26"},
        "after": {"app": "Microsoft Outlook", "window_title": "Vacation Plans — Personal", "ocr_excerpt": "Hey! Are you free next weekend"},
        "ground_truth_new_episode": True,
        "ground_truth_activity": "unknown",
        "rationale": "Personal/unrelated activity — episode boundary",
    },
    {
        "id": "boundary-005",
        "description": "Same document, moderate content scroll",
        "current_episode": "Martinez Estate motion drafting",
        "before": {"app": "Microsoft Word", "window_title": "Motion to Dismiss — Martinez.docx", "ocr_excerpt": "INTRODUCTION"},
        "after": {"app": "Microsoft Word", "window_title": "Motion to Dismiss — Martinez.docx", "ocr_excerpt": "ARGUMENT"},
        "ground_truth_new_episode": False,
        "ground_truth_activity": "drafting",
        "rationale": "Same document, scrolled to new section — clear continuation",
    },
    {
        "id": "boundary-006",
        "description": "Calculator/admin tool between matter work",
        "current_episode": "Meridian Partners cash flow model",
        "before": {"app": "Microsoft Excel", "window_title": "Meridian_Cash_Flow.xlsx", "ocr_excerpt": "Revenue Projection 2026"},
        "after": {"app": "Calculator", "window_title": "Calculator", "ocr_excerpt": ""},
        "ground_truth_new_episode": False,
        "ground_truth_activity": "analysis",
        "rationale": "Calculator is admin tool used in context of same matter — continuation",
    },
    {
        "id": "boundary-007",
        "description": "Completely different client matter after lunch break",
        "current_episode": "Smith v. Johnson research (morning)",
        "before": {"app": "Microsoft Outlook", "window_title": "Smith v. Johnson email", "ocr_excerpt": "Regarding the discovery schedule"},
        "after": {"app": "Adobe Acrobat", "window_title": "Lee_Commercial_Lease_Agreement.pdf", "ocr_excerpt": "COMMERCIAL LEASE AGREEMENT"},
        "ground_truth_new_episode": True,
        "ground_truth_activity": "review",
        "rationale": "Completely different client and matter — new episode",
    },
    {
        "id": "boundary-008",
        "description": "Team call about current matter (same matter context)",
        "current_episode": "Roberts Family Trust tax research",
        "before": {"app": "Microsoft Word", "window_title": "199A Analysis — Roberts Trust.docx", "ocr_excerpt": "QUALIFIED BUSINESS INCOME"},
        "after": {"app": "Zoom", "window_title": "Roberts Trust Planning Meeting", "ocr_excerpt": ""},
        "ground_truth_new_episode": False,
        "ground_truth_activity": "correspondence",
        "rationale": "Meeting about same matter — continue episode, activity becomes correspondence",
    },
    {
        "id": "boundary-009",
        "description": "Browser tab switch: same domain, different matter research",
        "current_episode": "Smith patent research",
        "before": {"app": "Google Chrome", "window_title": "USPTO — US9876543B2", "ocr_excerpt": "PATENT CLAIMS"},
        "after": {"app": "Google Chrome", "window_title": "USPTO — US1234567B1", "ocr_excerpt": "PATENT ABSTRACT"},
        "ground_truth_new_episode": False,
        "ground_truth_activity": "research",
        "rationale": "Same research activity, same domain — ambiguous but likely continuation",
    },
    {
        "id": "boundary-010",
        "description": "Distinct financial client after same-day accounting work",
        "current_episode": "Roberts Family Trust 199A analysis",
        "before": {"app": "Microsoft Word", "window_title": "199A Analysis — Roberts Trust.docx", "ocr_excerpt": "PASS-THROUGH INCOME"},
        "after": {"app": "Microsoft Excel", "window_title": "Apex_Q3_Inventory_Variance.xlsx", "ocr_excerpt": "INVENTORY VARIANCE ANALYSIS"},
        "ground_truth_new_episode": True,
        "ground_truth_activity": "analysis",
        "rationale": "Different client and matter entirely — new episode",
    },
]


def main() -> None:
    episodes_path = FIXTURES_DIR / "episodes.json"
    boundaries_path = FIXTURES_DIR / "boundary_scenarios.json"

    with open(episodes_path, "w") as f:
        json.dump(EPISODES, f, indent=2)
    print(f"Written {len(EPISODES)} episode fixtures → {episodes_path}")

    with open(boundaries_path, "w") as f:
        json.dump(BOUNDARY_SCENARIOS, f, indent=2)
    print(f"Written {len(BOUNDARY_SCENARIOS)} boundary scenarios → {boundaries_path}")


if __name__ == "__main__":
    main()
