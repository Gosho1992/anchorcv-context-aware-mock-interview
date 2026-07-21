"""
ATS Shield — Deterministic keyword extraction and matching.

Phase 1 is intentionally ML-free: no embeddings, no spaCy, no transformers.
Keyword detection relies on a hardcoded skills dictionary (500+ entries) plus
regex word-boundary matching that copes with symbol-heavy skills (c++, c#,
.net, node.js, ci/cd, scikit-learn, etc.).
"""

import re
from typing import Dict, List

# ---------------------------------------------------------------------------
# SKILLS_DICT — 500+ skills grouped by category.
# Stored lowercase so matching can be case-insensitive without re-lowering.
# ---------------------------------------------------------------------------
SKILLS_DICT: Dict[str, List[str]] = {
    "programming": [
        "python", "java", "javascript", "typescript", "c", "c++", "c#", "go",
        "golang", "rust", "ruby", "php", "swift", "kotlin", "scala", "perl",
        "r", "matlab", "objective-c", "dart", "elixir", "erlang", "haskell",
        "clojure", "lua", "groovy", "f#", "visual basic", "vba", "cobol",
        "fortran", "assembly", "bash", "shell scripting", "powershell",
        "solidity", "julia", "ocaml", "lisp", "scheme", "prolog", "abap",
        "apex", "pl/sql", "t-sql", "racket", "crystal", "nim", "zig",
    ],
    "frontend": [
        "react", "react.js", "angular", "vue", "vue.js", "svelte", "next.js",
        "nuxt", "nuxt.js", "redux", "mobx", "zustand", "recoil", "jquery",
        "html", "html5", "css", "css3", "sass", "scss", "less", "tailwind",
        "tailwind css", "bootstrap", "material ui", "chakra ui", "ant design",
        "styled components", "emotion", "webpack", "vite", "rollup", "parcel",
        "babel", "esbuild", "gatsby", "remix", "astro", "solidjs", "preact",
        "ember", "backbone", "alpine.js", "lit", "stencil", "storybook",
        "framer motion", "gsap", "three.js", "d3.js", "chart.js", "webgl",
        "progressive web apps", "responsive design", "web components",
        "accessibility", "wcag", "figma", "adobe xd", "sketch",
    ],
    "backend": [
        "node.js", "express", "express.js", "nestjs", "fastify", "koa",
        "django", "flask", "fastapi", "tornado", "pyramid", "spring",
        "spring boot", "spring mvc", "hibernate", "jakarta ee", "quarkus",
        "micronaut", "ruby on rails", "rails", "sinatra", "laravel",
        "symfony", "codeigniter", "asp.net", "asp.net core", ".net",
        ".net core", "gin", "echo", "fiber", "actix", "rocket", "phoenix",
        "graphql", "rest", "rest api", "restful", "grpc", "soap",
        "websockets", "microservices", "serverless", "rabbitmq", "kafka",
        "apache kafka", "celery", "redis queue", "message queue", "nginx",
        "apache", "gunicorn", "uvicorn", "tomcat", "oauth", "oauth2", "jwt",
        "openid connect", "saml", "api gateway",
    ],
    "database": [
        "sql", "mysql", "postgresql", "postgres", "sqlite", "mariadb",
        "oracle", "oracle db", "microsoft sql server", "sql server",
        "mongodb", "cassandra", "couchdb", "dynamodb", "redis", "memcached",
        "elasticsearch", "opensearch", "neo4j", "arangodb", "influxdb",
        "timescaledb", "cockroachdb", "firebase", "firestore", "supabase",
        "snowflake", "bigquery", "redshift", "databricks", "clickhouse",
        "hbase", "hive", "presto", "trino", "db2", "couchbase", "etcd",
        "database design", "data modeling", "query optimization",
        "indexing", "normalization", "stored procedures", "orm",
        "sqlalchemy", "prisma", "sequelize", "typeorm", "pgvector",
    ],
    "cloud": [
        "aws", "amazon web services", "azure", "microsoft azure", "gcp",
        "google cloud", "google cloud platform", "ec2", "s3", "lambda",
        "aws lambda", "cloudfront", "route 53", "rds", "aurora", "eks",
        "ecs", "fargate", "cloudformation", "iam", "vpc", "sqs", "sns",
        "step functions", "azure functions", "azure devops", "aks",
        "blob storage", "cosmos db", "cloud run", "cloud functions", "gke",
        "app engine", "cloud storage", "pub/sub", "digitalocean", "heroku",
        "vercel", "netlify", "cloudflare", "linode", "openstack",
        "cloud architecture", "cloud migration", "cost optimization",
        "serverless framework", "elastic beanstalk", "cloudwatch",
    ],
    "devops": [
        "docker", "kubernetes", "k8s", "helm", "terraform", "ansible",
        "puppet", "chef", "vagrant", "packer", "jenkins", "gitlab ci",
        "github actions", "circleci", "travis ci", "teamcity", "bamboo",
        "argo cd", "argocd", "flux", "spinnaker", "ci/cd", "continuous integration",
        "continuous deployment", "continuous delivery", "git", "github",
        "gitlab", "bitbucket", "svn", "mercurial", "prometheus", "grafana",
        "datadog", "new relic", "splunk", "elk stack", "logstash", "kibana",
        "fluentd", "opentelemetry", "jaeger", "pagerduty", "sentry",
        "infrastructure as code", "configuration management", "sre",
        "site reliability engineering", "observability", "monitoring",
        "load balancing", "service mesh", "istio", "linkerd", "consul",
        "vault", "nomad",
    ],
    "data": [
        "data analysis", "data analytics", "data engineering", "data science",
        "etl", "elt", "data pipeline", "data warehouse", "data lake",
        "data lakehouse", "apache spark", "spark", "pyspark", "hadoop",
        "mapreduce", "airflow", "apache airflow", "dbt", "luigi", "dagster",
        "prefect", "kafka streams", "flink", "apache flink", "beam",
        "pandas", "numpy", "scipy", "polars", "dask", "modin", "matplotlib",
        "seaborn", "plotly", "bokeh", "tableau", "power bi", "looker",
        "qlik", "superset", "metabase", "excel", "google sheets", "sas",
        "spss", "stata", "statistics", "statistical analysis", "ab testing",
        "a/b testing", "data visualization", "data cleaning", "data wrangling",
        "feature engineering", "etl pipelines", "data governance",
        "data quality", "great expectations",
    ],
    "ai_ml": [
        "machine learning", "deep learning", "neural networks", "tensorflow",
        "pytorch", "keras", "scikit-learn", "sklearn", "xgboost", "lightgbm",
        "catboost", "hugging face", "transformers", "nlp",
        "natural language processing", "computer vision", "opencv", "yolo",
        "cnn", "rnn", "lstm", "gru", "transformer", "attention mechanism",
        "bert", "gpt", "llm", "large language models", "generative ai",
        "prompt engineering", "rag", "retrieval augmented generation",
        "fine-tuning", "reinforcement learning", "supervised learning",
        "unsupervised learning", "semi-supervised learning", "clustering",
        "classification", "regression", "random forest", "gradient boosting",
        "support vector machines", "svm", "k-means", "pca", "model deployment",
        "mlops", "mlflow", "kubeflow", "feature store", "model serving",
        "onnx", "tensorrt", "langchain", "llamaindex", "vector database",
        "embeddings", "recommendation systems", "anomaly detection",
        "time series forecasting", "spacy", "nltk", "gensim",
    ],
    "mobile": [
        "ios", "android", "swiftui", "jetpack compose", "react native",
        "flutter", "xamarin", "ionic", "cordova", "capacitor",
        "android studio", "xcode", "uikit", "core data", "room", "retrofit",
        "alamofire", "mobile development", "app store", "google play",
        "push notifications", "mobile ui", "responsive mobile design",
        "kotlin multiplatform",
    ],
    "testing": [
        "unit testing", "integration testing", "end-to-end testing",
        "e2e testing", "test automation", "pytest", "unittest", "jest",
        "mocha", "chai", "jasmine", "junit", "testng", "selenium",
        "cypress", "playwright", "puppeteer", "appium", "cucumber",
        "behave", "robot framework", "postman", "soapui", "jmeter",
        "locust", "k6", "load testing", "performance testing",
        "regression testing", "test driven development", "tdd", "bdd",
        "code coverage", "mocking", "qa", "quality assurance",
    ],
    "security": [
        "cybersecurity", "information security", "application security",
        "network security", "penetration testing", "pen testing",
        "ethical hacking", "vulnerability assessment", "owasp",
        "security auditing", "encryption", "cryptography", "tls", "ssl",
        "pki", "firewalls", "ids", "ips", "siem", "soc", "incident response",
        "threat modeling", "threat intelligence", "malware analysis",
        "forensics", "identity and access management", "zero trust",
        "gdpr", "hipaa", "soc 2", "iso 27001", "pci dss", "compliance",
        "burp suite", "metasploit", "nmap", "wireshark", "kali linux",
    ],
    "soft": [
        "communication", "teamwork", "collaboration", "leadership",
        "problem solving", "critical thinking", "creativity", "adaptability",
        "time management", "organization", "attention to detail",
        "analytical skills", "decision making", "conflict resolution",
        "negotiation", "presentation skills", "public speaking",
        "active listening", "emotional intelligence", "mentoring",
        "coaching", "self-motivated", "proactive", "flexibility",
        "interpersonal skills", "work ethic", "accountability",
        "cross-functional collaboration", "customer focus",
        "results oriented", "strategic thinking", "multitasking",
        "prioritization", "resilience", "empathy", "relationship building",
        "facilitation", "storytelling", "continuous learning",
    ],
    "business": [
        "project management", "product management", "agile", "scrum",
        "kanban", "waterfall", "lean", "six sigma", "jira", "confluence",
        "trello", "asana", "monday.com", "notion", "pmp", "prince2",
        "safe", "product roadmap", "backlog management", "sprint planning",
        "stakeholder management", "business analysis", "requirements gathering",
        "user stories", "okrs", "kpis", "budgeting", "forecasting",
        "financial modeling", "financial analysis", "accounting",
        "salesforce", "hubspot", "crm", "erp", "sap", "marketing",
        "digital marketing", "seo", "sem", "content marketing",
        "social media marketing", "google analytics", "market research",
        "competitive analysis", "go-to-market strategy", "sales",
        "account management", "operations management", "supply chain",
        "process improvement", "change management", "vendor management",
        "risk management", "business development", "p&l management",
    ],
}


def _all_skills() -> List[str]:
    """Flat, de-duplicated list of every skill (kept long-first for greedy match)."""
    seen = set()
    out: List[str] = []
    for skills in SKILLS_DICT.values():
        for raw in skills:
            s = raw.strip().lower()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    # Match longer / more specific phrases first ("react native" before "react").
    out.sort(key=len, reverse=True)
    return out


_ALL_SKILLS = _all_skills()

# Characters that count as part of a "word" for boundary purposes. We include
# + and # so that the bare languages "c"/"r" do NOT match inside "c++" / "c#",
# while leaving out '.', '-' and '/' so ordinary words followed by punctuation
# (e.g. "React." or "machine learning.") still match, and symbol skills like
# ".net", "node.js", "ci/cd", "scikit-learn" match as whole tokens.
_WORD = r"a-z0-9+#"


def _skill_in_text(skill: str, text_lower: str) -> bool:
    """True if `skill` appears as a standalone token in already-lowercased text."""
    s = skill.strip().lower()
    if not s:
        return False
    pattern = re.escape(s)
    guarded = rf"(?<![{_WORD}]){pattern}(?![{_WORD}])"
    try:
        return re.search(guarded, text_lower) is not None
    except re.error:
        return s in text_lower


def _partial_match(skill: str, text_lower: str) -> bool:
    """
    A multi-word skill is a *partial* match when some — but not all — of its
    significant tokens are present (e.g. JD wants 'react native', resume has
    only 'react').
    """
    tokens = [t for t in re.split(r"[\s/]+", skill.lower()) if len(t) > 2]
    if len(tokens) < 2:
        return False
    hits = sum(1 for t in tokens if _skill_in_text(t, text_lower))
    return 0 < hits < len(tokens)


def extract_keywords_deterministic(job_description: str) -> List[str]:
    """
    Scan the job description for any skill present in SKILLS_DICT and return the
    list of detected required keywords (original dictionary spelling, ordered by
    first appearance in the JD).
    """
    if not job_description:
        return []
    jd_lower = job_description.lower()
    found: List[str] = []
    seen = set()
    for skill in _ALL_SKILLS:
        if skill in seen:
            continue
        if _skill_in_text(skill, jd_lower):
            found.append(skill)
            seen.add(skill)
    # Order by position of first occurrence in the JD for a natural reading order.
    found.sort(key=lambda s: jd_lower.find(s))
    return found


def compare_keywords(jd_keywords: List[str], resume_text: str) -> Dict:
    """
    Compare JD-required keywords against the resume text.

    Returns a dict with:
        present           — exact standalone matches
        missing           — not found at all
        partial           — some (not all) tokens of a multi-word skill present
        match_percentage  — (present + 0.5*partial) / total * 100
    """
    resume_lower = (resume_text or "").lower()
    present: List[str] = []
    missing: List[str] = []
    partial: List[str] = []

    for kw in jd_keywords:
        if _skill_in_text(kw, resume_lower):
            present.append(kw)
        elif _partial_match(kw, resume_lower):
            partial.append(kw)
        else:
            missing.append(kw)

    total = len(jd_keywords)
    if total == 0:
        match_percentage = 0.0
    else:
        match_percentage = round((len(present) + 0.5 * len(partial)) / total * 100, 1)

    return {
        "present": present,
        "missing": missing,
        "partial": partial,
        "match_percentage": match_percentage,
        "total_required": total,
    }
