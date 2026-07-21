# localisation.py
"""
Country-specific CV & Cover Letter rules.
Injected into prompts at generation time.
No database tables needed — just a Python dict.
"""

LOCALISATION_RULES = {
    "UK": """
- CV length: 2 pages maximum
- Spelling: British English (organise, colour, programme, analyse)
- Tone: Understated competence, evidence over claims. Avoid exaggeration.
- Personal details: Name, email, phone, LinkedIn only. NO photo, NO date of birth.
- Phrasing: Use "whilst", "amongst", "undertook", "engaged with"
- Cover letter: Open with a reference to the specific role, not the candidate.
""",
    "US": """
- CV length: 1 page (2 pages if senior/10+ years)
- Spelling: American English (organize, color, program, analyze)
- Tone: Confident, achievement-focused, warm but direct. "I led" is fine.
- Personal details: Name, email, phone, LinkedIn, city/state. NO photo, NO date of birth.
- Phrasing: Short, punchy sentences. Action verbs at the start of bullets.
- Cover letter: Strong hook, metrics in first paragraph, direct ask.
""",
    "Germany": """
- CV length: 1-2 pages (German employers expect a complete but concise CV)
- Spelling: British English usually accepted, but formal German-style layout.
- Tone: Formal, precise, credentials-first. Avoid casual language.
- Personal details: Include date of birth (DD.MM.YYYY), nationality, full address, professional photo placeholder (candidate should attach a real photo).
- Section order: Personal Data -> Professional Experience -> Education -> Skills -> Languages -> Hobbies (optional)
- Cover letter: Formal salutation ("Sehr geehrte Damen und Herren"), reference to qualifications, no humour.
""",
    "Australia": """
- CV length: 2-3 pages
- Spelling: British English (organise, colour, programme)
- Tone: Direct with humility. Self-deprecation acceptable if genuine. Avoid corporate buzzwords.
- Personal details: Name, email, phone, LinkedIn. NO photo, NO date of birth.
- Phrasing: Short sentences, plain English. Use "I've" rather than "I have". Avoid "utilise" -> "use".
- Cover letter: Friendly, direct, mention any local connections.
""",
    "Canada": """
- CV length: 1-2 pages
- Spelling: Mix of British/American acceptable, but consistency matters. Use "colour" but "organize".
- Tone: Similar to US but slightly more modest. "I contributed to" sometimes better than "I led".
- Personal details: Name, email, phone, LinkedIn, city. NO photo, NO date of birth.
- Phrasing: "Among" vs "amongst". Avoid overly British or overly American extremes.
""",
    "Singapore": """
- CV length: 2 pages
- Spelling: British English (organise, colour, programme)
- Tone: Formal, respectful, emphasis on team and systems over individual heroics.
- Personal details: Name, email, phone, LinkedIn. Nationality sometimes requested. Professional photo often expected (include placeholder).
- Phrasing: "Liaised with", "collaborated with", "contributed to". Avoid aggressive self-promotion.
""",
    "Netherlands": """
- CV length: 1-2 pages
- Spelling: British English commonly used.
- Tone: Direct, flat hierarchy. "I did X" is fine. Honesty valued over hyperbole.
- Personal details: Name, email, phone, LinkedIn. Photo sometimes included (professional), no date of birth.
- Phrasing: Short, factual sentences. No buzzwords. Mention language skills.
""",
}

# Fallback for unknown countries
DEFAULT_RULE = """
- CV length: 1-2 pages
- Spelling: British English
- Tone: Professional but approachable
- Personal details: Name, email, phone, LinkedIn. No photo unless explicitly requested.
"""

_COUNTRY_KEYWORDS = {
    "UK": [
        "united kingdom", " uk ", "british", "england", "scotland", "wales",
        "london", "manchester", "edinburgh", "birmingham", "glasgow",
        "leeds", "liverpool", "bristol", "sheffield", "cambridge", "oxford",
    ],
    "US": [
        "united states", "usa", " us ", "america", "american",
        "california", "new york", "texas", "washington", "boston",
        "san francisco", "chicago", "seattle", "los angeles", "austin",
        "new jersey", "massachusetts", "florida",
    ],
    "Germany": [
        "germany", "deutschland", "german", "gmbh", "ag ", "berlin",
        "munich", "munchen", "frankfurt", "hamburg", "koln", "cologne",
        "dusseldorf", "stuttgart", "dortmund",
    ],
    "Australia": [
        "australia", "australian", "sydney", "melbourne", "brisbane",
        "perth", "adelaide", "canberra", "gold coast",
    ],
    "Canada": [
        "canada", "canadian", "toronto", "vancouver", "montreal",
        "calgary", "ottawa", "edmonton", "quebec",
    ],
    "Singapore": ["singapore", "singaporean"],
    "Netherlands": [
        "netherlands", "holland", "dutch", "amsterdam", "rotterdam",
        "utrecht", "eindhoven", "the hague", "den haag",
    ],
}


def detect_target_country(job_description: str):
    """
    Detect target country from job description text.
    Returns a key from LOCALISATION_RULES, or None if unclear.
    """
    text = " " + (job_description or "").lower() + " "

    for country, keywords in _COUNTRY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return country

    return None  # will use DEFAULT_RULE


def get_localisation_rule(job_description: str):
    """
    Return (rule_string, country_name_or_None) for a given JD.
    The country name is used to label prompts; rule_string is injected verbatim.
    """
    country = detect_target_country(job_description)
    if country and country in LOCALISATION_RULES:
        return LOCALISATION_RULES[country], country
    return DEFAULT_RULE, None


def build_localisation_block(job_description: str) -> str:
    """
    Return a ready-to-inject prompt block.
    Usage: append this to any system prompt.
    """
    rule, country = get_localisation_rule(job_description)
    label = country if country else "Generic (no country detected)"
    return (
        f"\n\nLOCALISATION REQUIREMENTS [{label}]:\n"
        f"{rule.strip()}\n\n"
        "Apply these rules strictly throughout every section of the output. "
        "If the rule specifies British English, use British spelling everywhere. "
        "If the rule says no photo, do not mention a photo. "
        "If the rule says include date of birth, add a placeholder [DOB: DD.MM.YYYY] "
        "in the personal details section."
    )


def build_seniority_block(resume_text: str) -> str:
    """
    Detect approximate seniority from resume text and return a calibration block.
    Counts year-spans and senior title signals.
    """
    import re
    text = (resume_text or "").lower()

    # Count explicit year mentions (rough proxy for years of experience)
    years = re.findall(r"\b(19|20)\d{2}\b", text)
    if years:
        year_ints = [int(y) for y in years]
        span = max(year_ints) - min(year_ints)
    else:
        span = 0

    # Senior title signals
    senior_signals = [
        "director", "vp ", "vice president", "chief", "head of", "principal",
        "staff engineer", "distinguished", "partner", "c-suite",
    ]
    is_senior_title = any(s in text for s in senior_signals)

    if is_senior_title or span >= 10:
        return (
            "\n\nSENIORITY CALIBRATION [Senior / Leadership]:\n"
            "Tone: Strategic, leadership-focused. Emphasise vision, team impact, "
            "budget/P&L responsibility, and organisational change. "
            "Use 'led', 'directed', 'architected', 'scaled', 'owned'."
        )
    if span >= 4:
        return (
            "\n\nSENIORITY CALIBRATION [Mid-level]:\n"
            "Tone: Confident, results-oriented. Use 'led', 'managed', 'delivered' "
            "with specific metrics wherever possible. Balance team contributions "
            "with individual achievements."
        )
    return (
        "\n\nSENIORITY CALIBRATION [Early career]:\n"
        "Tone: Enthusiastic and eager. Reference coursework, projects, and "
        "transferable skills. Use 'built', 'created', 'contributed to', 'supported'. "
        "Avoid overstating seniority."
    )
