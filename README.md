# Provenance Guard

Flask backend that classifies whether creative text is likely human-written or AI-generated. Uses three detection signals, returns a confidence score and transparency label, logs every decision, and supports appeals.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env` (do not commit):

```
GROQ_API_KEY=your_key_here
```

```bash
python app.py
```

Server runs at `http://127.0.0.1:5001` (port 5001 avoids macOS AirPlay using 5000).

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/submit` | Submit content for analysis |
| `POST` | `/appeal` | Contest a classification |
| `POST` | `/verify` | Creator verification (stretch) |
| `GET` | `/log` | Audit log |
| `GET` | `/analytics` | Metrics JSON (stretch) |
| `GET` | `/dashboard` | Dashboard UI (stretch) |
| `GET` | `/ui` | Submit form UI (stretch) |

---

## Architecture Overview

Path from submission to transparency label:

1. Client sends `POST /submit` with `creator_id` and content (`text`, `image_description`, or `metadata`).
2. **Rate limiter** checks per-IP limits (10/min, 100/day). Over limit → HTTP 429.
3. **Input validation** — required fields checked; `content_id` (UUID) assigned.
4. **Signal 1 (LLM)** — Groq returns `llm_score` (0 = human, 1 = AI).
5. **Signal 2 (Stylometrics)** — Python computes `stylometric_score` from sentence structure.
6. **Signal 3 (Phrase patterns)** — Python computes `phrase_score` from AI-style phrasing.
7. **Ensemble scorer** — weighted blend → `confidence` score.
8. **Attribution** — maps to `likely_ai`, `uncertain`, or `likely_human`.
9. **Label generator** — maps attribution to plain-language label text.
10. **Storage** — SQLite + JSON audit log; JSON response returned.

**Appeal path:** `POST /appeal` → lookup by `content_id` → status `under_review` → appeal logged alongside original decision.

---

## Detection Signals

### Signal 1: LLM classifier (Groq — `llama-3.3-70b-versatile`)

- **What it measures:** Semantic and stylistic coherence — tone, phrasing, whether writing reads natural or machine-polished.
- **Output:** `llm_score` (0.0–1.0)
- **Why I chose it:** Reads context holistically; catches polished AI prose and casual human voice.
- **What it misses:** Short text, formal academic writing, lightly edited AI drafts.

### Signal 2: Stylometric heuristics (Python)

- **What it measures:** Sentence-length standard deviation, type-token ratio, punctuation density.
- **Output:** `stylometric_score` (0.0–1.0)
- **Why I chose it:** Structural signal with no API cost; catches uniform rhythm the LLM can miss.
- **What it misses:** Meaning — repetitive poetry or rigid essays can score wrong.

### Signal 3: Phrase pattern fingerprint (Python)

- **What it measures:** Density of AI transition phrases ("Furthermore," "It is important to note") and uniformity of sentence openers.
- **Output:** `phrase_score` (0.0–1.0)
- **Why I chose it:** Lexical signal independent of semantics and statistics.
- **What it misses:** Formal human writers who use academic transition words.

Signals are combined in a weighted ensemble (see Confidence Scoring). When they disagree, attribution stays at `uncertain` rather than forcing a strong AI label.

---

## Confidence Scoring

**How signals are combined:**

```
confidence = (0.5 × llm_score) + (0.3 × stylometric_score) + (0.2 × phrase_score)
```

**Thresholds:**

| Score | Attribution |
|---|---|
| ≥ 0.75 | `likely_ai` |
| 0.40 – 0.74 | `uncertain` |
| ≤ 0.39 | `likely_human` |

If signal scores spread by more than 0.30, or cross-conflict (one says human, others say AI), attribution is capped at `uncertain` unless confidence ≤ 0.30.

**How I validated scores:** Tested four inputs from the project spec — corporate AI boilerplate, casual human ramen review, formal academic essay, lightly edited AI. Clearly human and clearly AI produced different scores; borderline cases landed in the uncertain band.

### Example 1 — higher-confidence case

```
Text: "Artificial intelligence represents a transformative paradigm shift in modern
society. It is important to note that while the benefits of AI are numerous, it is
equally essential to consider the ethical implications. Furthermore, stakeholders
across various sectors must collaborate to ensure responsible deployment."

llm_score: 0.80
stylometric_score: 0.55
phrase_score: 0.72
confidence: 0.70
attribution: uncertain
```

### Example 2 — lower-confidence case

```
Text: "ok so i finally tried that new ramen place downtown and honestly? underwhelming.
the broth was fine but they put WAY too much sodium in it and i was thirsty for like
three hours after. my friend got the spicy version and said it was better. probably
won't go back unless someone drags me there"

llm_score: 0.20
stylometric_score: 0.47
phrase_score: 0.18
confidence: 0.31
attribution: likely_human
```

These two produce noticeably different confidence scores (0.70 vs 0.31) and different label text.

---

## Transparency Label

Three variants — exact text shown to readers (not just a score):

| Attribution | Label text |
|---|---|
| **High-confidence AI** (`likely_ai`) | "AI-Generated — This piece shows strong signs of machine-generated writing. The phrasing, structure, and style closely match patterns typical of AI text. Creators can request a review if they believe this label is incorrect." |
| **Uncertain** (`uncertain`) | "Authorship Unclear — We couldn't confidently determine whether this was written by a person or generated by AI. The writing style falls in an ambiguous range. If you're the creator and this doesn't seem right, you can request a human review." |
| **High-confidence human** (`likely_human`) | "Human-Written — This piece appears to be written by a person. The voice, rhythm, and word choices reflect natural human expression rather than machine-generated patterns." |

The label text changes by attribution category — a reader sees different wording, not just a different number.

---

## Rate Limiting

| Limit | Value |
|---|---|
| Per minute | 10 requests / IP |
| Per day | 100 requests / IP |

Applied to `POST /submit` only (Flask-Limiter, `storage_uri="memory://"`).

**Why these limits:** A creator might submit 1–3 pieces per session. Ten per minute allows normal use but stops a script from flooding the API. One hundred per day blocks sustained abuse. Appeals are not rate-limited.

**Evidence** — 12 rapid requests (after one earlier submit in the same window):

```
200
200
200
200
200
200
200
200
200
429
429
429
```

---

## Appeals Workflow

`POST /appeal` accepts `content_id` and `creator_reasoning` (min 10 characters). Status updates to `under_review`; appeal is logged next to the original classification. Duplicate appeals return 409. No automated re-classification.

---

## Audit Log

`GET /log` returns structured JSON. Sample of three entries (one with an appeal):

```json
{
  "entries": [
    {
      "content_id": "efca1c51-7975-4edb-a324-1f1bbf1263b2",
      "creator_id": "m4-ai",
      "timestamp": "2026-07-01T04:01:28.457044+00:00",
      "attribution": "uncertain",
      "confidence": 0.68,
      "llm_score": 0.8,
      "stylometric_score": 0.5,
      "phrase_score": 0.65,
      "status": "classified"
    },
    {
      "content_id": "e1594781-1a68-451d-8c64-6e8fa17b4d7d",
      "creator_id": "demo-user",
      "timestamp": "2026-07-01T04:13:53.000000+00:00",
      "attribution": "likely_human",
      "confidence": 0.288,
      "llm_score": 0.2,
      "stylometric_score": 0.421,
      "phrase_score": 0.15,
      "status": "classified"
    },
    {
      "content_id": "b9acb9da-5890-4c4b-b423-fe2556b68ceb",
      "creator_id": "appeal-test-user",
      "timestamp": "2026-07-01T04:03:58.464251+00:00",
      "attribution": "uncertain",
      "confidence": 0.32,
      "llm_score": 0.2,
      "stylometric_score": 0.5,
      "phrase_score": 0.45,
      "status": "under_review",
      "appeal_reasoning": "I wrote this poem myself during a writing workshop last month.",
      "appeal_timestamp": "2026-07-01T04:03:58.604146+00:00"
    }
  ]
}
```

---

## Known Limitations

**Formal academic human writing** is what the system gets wrong most often. Scholarly prose uses consistent structure and hedging language ("extensively studied," "fundamental tension") that overlaps with AI patterns. The LLM scores it high and stylometrics see uniform sentences — so human essays often land in `uncertain` instead of `likely_human`. That's a property of both signals, not just bad luck.

**Very short text** (< 30 words) is also unreliable: stylometrics default to 0.5 and the LLM has little context, so short human posts often get `uncertain`.

---

## Spec Reflection

**How the spec helped:** Writing `planning.md` before coding forced me to define thresholds and label text upfront. When I built `scoring.py`, I had concrete numbers to implement against instead of guessing mid-build.

**Where I diverged:** The plan used raw sentence-length variance, but testing showed one long sentence in AI text inflated variance and made AI writing look human. I switched to standard deviation, which fit the intent better. I also added a third phrase-pattern signal and ensemble weights for the stretch feature.

---

## AI Usage

### Instance 1: Flask app + LLM classifier (Milestone 3)

- **What I asked for:** Flask skeleton, `POST /submit`, Groq classifier with JSON output, audit log, SQLite store — using my detection signals section and architecture diagram from `planning.md`.
- **What it produced:** Working route stubs and Groq integration in one file.
- **What I changed:** Split into separate modules; fixed the LLM prompt after Groq rejected malformed JSON; added regex fallback for parse failures.

### Instance 2: Stylometrics + scoring (Milestone 4)

- **What I asked for:** `compute_stylometric_score()` and `combine_scores()` / `determine_attribution()` per spec weights and thresholds.
- **What it produced:** Stylometric and scoring modules with weighted blending.
- **What I changed:** Switched variance to std dev after benchmark testing; added cross-signal conflict detection for edited AI text.

### Instance 3: Appeals + rate limiting (Milestone 5)

- **What I asked for:** `POST /appeal`, Flask-Limiter on `/submit`, audit log appeal fields.
- **What it produced:** Appeal endpoint with 404/409 handling and rate limiter setup.
- **What I changed:** Fixed missing `Optional` import; added truncated `text` to log entries; limited rate limiting to `/submit` only.

---

## Stretch Features

- **Ensemble (3 signals):** weights 0.5 / 0.3 / 0.2; all scores returned on every submit.
- **Provenance certificate:** `POST /verify` → verified badge on `likely_human` results.
- **Analytics dashboard:** `GET /dashboard` and `GET /analytics`.
- **Multi-modal:** `content_type` of `text`, `image_description`, or `metadata`.
- **UI:** `GET /ui` for browser submissions.

See `planning.md` → Stretch Features for full spec.
