# Provenance Guard

A Flask backend that classifies whether submitted creative text is likely human-written or AI-generated. It combines two independent detection signals, returns a confidence score with plain-language transparency labels, logs every decision for accountability, and lets creators appeal misclassifications.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate          # Mac/Linux
pip install -r requirements.txt
```

Create a `.env` file (never commit it):

```
GROQ_API_KEY=your_key_here
```

Run the server:

```bash
python app.py
```

Server starts at `http://127.0.0.1:5001` (port 5001 avoids a conflict with macOS AirPlay Receiver, which uses 5000).

### API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/submit` | Submit text for attribution analysis |
| `POST` | `/appeal` | Contest a classification |
| `GET` | `/log` | View structured audit log entries |

**Submit example:**

```bash
curl -s -X POST http://127.0.0.1:5001/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "Your poem or story here...", "creator_id": "user-123"}'
```

**Appeal example:**

```bash
curl -s -X POST http://127.0.0.1:5001/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "PASTE-UUID-HERE", "creator_reasoning": "I wrote this myself because..."}'
```

---

## Architecture Overview

A submission follows this path from input to transparency label:

1. **Rate limiter** — Flask-Limiter checks per-IP limits before any processing.
2. **Validation** — `POST /submit` requires `text` and `creator_id`; assigns a UUID `content_id`.
3. **Signal 1 (LLM)** — Groq `llama-3.3-70b-versatile` returns an `ai_likelihood` score (0 = human, 1 = AI).
4. **Signal 2 (Stylometrics)** — Pure Python computes sentence-length std dev, type-token ratio, and punctuation density.
5. **Confidence scorer** — Weighted blend: `0.6 × llm_score + 0.4 × stylometric_score`.
6. **Attribution** — Maps combined score to `likely_ai`, `uncertain`, or `likely_human` with signal-disagreement rules.
7. **Label generator** — Maps attribution to plain-language transparency text.
8. **Storage** — SQLite persists the submission; JSON audit log records the decision.
9. **Response** — JSON returned with `content_id`, scores, attribution, confidence, and label.

**Appeal flow:** `POST /appeal` looks up the submission by `content_id`, sets status to `under_review`, and updates the audit log with `appeal_reasoning` while preserving the original classification.

```
POST /submit → rate limit → validate → LLM signal → stylometric signal
           → combine scores → attribution → label → SQLite + audit log → JSON response

POST /appeal → lookup content_id → update status → log appeal → confirmation
```

### Project Files

| File | Role |
|---|---|
| `app.py` | Flask routes, rate limiting, request handling |
| `signals/llm_classifier.py` | Groq LLM authorship classifier |
| `signals/stylometrics.py` | Structural text heuristics |
| `scoring.py` | Score combination, attribution, label generation |
| `store.py` | SQLite submission persistence |
| `audit_log.py` | Append-only JSON audit log |
| `planning.md` | Pre-implementation spec and architecture |

---

## Detection Signals

### Signal 1: LLM Classifier (Groq)

| | |
|---|---|
| **Measures** | Semantic and stylistic coherence — tone, phrasing, naturalness |
| **Output** | `llm_score` float 0.0–1.0 (0 = human, 1 = AI) |
| **Why chosen** | Reads context holistically; catches polished AI prose and casual human voice |
| **Blind spots** | Can misread formal human writing as AI; short texts give little context; lightly edited AI may score mid-range |

### Signal 2: Stylometric Heuristics (Python)

| | |
|---|---|
| **Measures** | Sentence-length standard deviation, type-token ratio, punctuation density |
| **Output** | `stylometric_score` float 0.0–1.0 (0 = human-like variability, 1 = AI-like uniformity) |
| **Why chosen** | Independent structural signal — no API cost, fast, catches uniformity the LLM may miss |
| **Blind spots** | Cannot read meaning; repetitive poetry scores AI-like; formal essays with varied vocabulary score human-like on TTR |

These signals are genuinely independent (semantic vs. structural). When they disagree, the system leans toward `uncertain` rather than forcing a strong AI label — protecting human creators from false positives.

---

## Confidence Scoring

The `confidence` field is the combined **AI-likelihood** score:

```
confidence = (0.6 × llm_score) + (0.4 × stylometric_score)
```

| Score range | Attribution | Meaning |
|---|---|---|
| ≥ 0.75 | `likely_ai` | Strong evidence of AI generation |
| 0.40 – 0.74 | `uncertain` | Genuinely ambiguous |
| ≤ 0.39 | `likely_human` | Strong evidence of human authorship |

**Signal disagreement rule:** If signals differ by more than 0.30, or one says human while the other says AI (cross-conflict), attribution is capped at `uncertain` unless the combined score is very low (≤ 0.30).

### Validation

Tested with four deliberately chosen inputs spanning the confidence range:

| Input | llm | styl | confidence | attribution |
|---|---|---|---|---|
| Corporate AI boilerplate | 0.80 | 0.55 | 0.70 | uncertain |
| Casual human ramen review | 0.20 | 0.47 | 0.31 | likely_human |
| Formal academic essay | 0.80 | 0.55 | 0.70 | uncertain |
| Lightly edited AI paragraph | 0.20 | 0.56 | 0.35 | uncertain |

Clearly AI and clearly human produce noticeably different scores (0.70 vs 0.31). Borderline cases land in the uncertain band as intended.

### Example Submissions

**Higher-confidence case (corporate AI boilerplate):**

```
Text: "Artificial intelligence represents a transformative paradigm shift in modern
society. It is important to note that while the benefits of AI are numerous, it is
equally essential to consider the ethical implications. Furthermore, stakeholders
across various sectors must collaborate to ensure responsible deployment."

llm_score: 0.80 | stylometric_score: 0.55 | confidence: 0.70
attribution: uncertain
label: Authorship Unclear — ...
```

**Lower-confidence case (casual human review):**

```
Text: "ok so i finally tried that new ramen place downtown and honestly? underwhelming.
the broth was fine but they put WAY too much sodium in it and i was thirsty for like
three hours after. my friend got the spicy version and said it was better. probably
won't go back unless someone drags me there"

llm_score: 0.20 | stylometric_score: 0.47 | confidence: 0.31
attribution: likely_human
label: Human-Written — ...
```

**High-confidence AI case (uniform multi-sentence text where both signals agree):**

```
Text: "It is important to note that artificial intelligence continues to transform industries
worldwide. Furthermore, organizations must adopt responsible practices when deploying these
systems. Additionally, stakeholders should collaborate to ensure ethical outcomes. Moreover,
the benefits of innovation must be balanced with appropriate safeguards."

llm_score: 0.88 | stylometric_score: 0.82 | confidence: 0.856
attribution: likely_ai
label: AI-Generated — ...
```

The corporate boilerplate example above lands in `uncertain` (0.70) by design — stylometrics do not score it high enough to cross the 0.75 threshold. Uniform AI text with agreeing signals is required to reach the `likely_ai` label.

---

## Transparency Labels

Three label variants — exact text shown to readers:

| Attribution | Label text |
|---|---|
| **High-confidence AI** (`likely_ai`) | "AI-Generated — This piece shows strong signs of machine-generated writing. The phrasing, structure, and style closely match patterns typical of AI text. Creators can request a review if they believe this label is incorrect." |
| **Uncertain** (`uncertain`) | "Authorship Unclear — We couldn't confidently determine whether this was written by a person or generated by AI. The writing style falls in an ambiguous range. If you're the creator and this doesn't seem right, you can request a human review." |
| **High-confidence human** (`likely_human`) | "Human-Written — This piece appears to be written by a person. The voice, rhythm, and word choices reflect natural human expression rather than machine-generated patterns." |

---

## Rate Limiting

Applied to `POST /submit` only via Flask-Limiter:

| Limit | Value | Rationale |
|---|---|---|
| Per minute | 10 requests / IP | A real creator submits a few pieces per session; blocks rapid script flooding |
| Per day | 100 requests / IP | Prevents sustained abuse while allowing heavy legitimate use |

A typical creator might submit 1–3 pieces in a sitting. An adversary flooding the endpoint would hit the per-minute cap before exhausting API credits. Appeals (`POST /appeal`) are not rate-limited so creators can always contest a label.

**Evidence — 12 rapid requests in the same minute window:**

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

Requests 10–12 received HTTP 429 (Too Many Requests). One earlier `/submit` in the same window consumed the 10th allowed slot.

---

## Appeals Workflow

Creators contest a classification via `POST /appeal` with:

- `content_id` — UUID from the original `/submit` response
- `creator_reasoning` — free-text explanation (minimum 10 characters)

The system updates status to `under_review`, logs the appeal alongside the original decision, and returns a confirmation. Duplicate appeals return HTTP 409. No automated re-classification occurs.

---

## Audit Log Sample

`GET /log` returns structured JSON entries. Sample of three entries (including one appeal):

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
      "label": "Authorship Unclear — We couldn't confidently determine...",
      "status": "classified"
    },
    {
      "content_id": "c343981f-8793-4b83-a531-28d9a1e06d33",
      "creator_id": "m4-human",
      "timestamp": "2026-07-01T04:01:27.747381+00:00",
      "attribution": "uncertain",
      "confidence": 0.32,
      "llm_score": 0.2,
      "stylometric_score": 0.5,
      "label": "Authorship Unclear — We couldn't confidently determine...",
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
      "label": "Authorship Unclear — We couldn't confidently determine...",
      "status": "under_review",
      "appeal_reasoning": "I wrote this poem myself during a writing workshop last month.",
      "appeal_timestamp": "2026-07-01T04:03:58.604146+00:00"
    }
  ]
}
```

---

## Known Limitations

**Formal academic human writing** is the case our system handles poorest. Scholarly prose uses consistent sentence structure, field-specific vocabulary, and hedging language ("extensively studied," "fundamental tension") that mirrors AI patterns. Both signals lean AI-ish — the LLM scores polished prose high, and stylometrics see uniform sentence lengths. These submissions land in the `uncertain` band rather than `likely_human`, which is conservative but may frustrate academic authors. The appeals path exists for exactly this scenario.

**Very short submissions** (< 30 words) also perform poorly: stylometrics default to 0.5 (neutral) because there aren't enough sentences for reliable variance, and the LLM has limited context. Most short texts land in `uncertain`.

---

## Spec Reflection

**How the spec helped:** Writing `planning.md` before any code forced concrete decisions upfront — especially the confidence thresholds (0.75 / 0.39) and the three label texts. When implementing `scoring.py`, I could verify the generated code against specific numbers rather than discovering mid-build that 0.62 meant nothing.

**Where implementation diverged:** The spec defined sentence-length *variance* with thresholds 5 and 30, but in practice raw variance produced counterintuitive scores for the benchmark AI text (one long middle sentence inflated variance, making AI text look human). I switched the variance sub-metric to use **standard deviation** with thresholds 4 and 10, which better captures rhythmic uniformity while staying true to the spec's intent. I also added a **cross-signal conflict** check beyond the simple 0.30 gap rule, so cases like lightly edited AI (LLM says human, stylometrics say AI) land in `uncertain` instead of `likely_human`.

---

## AI Usage

### Instance 1: Flask app skeleton and LLM classifier (Milestone 3)

**Directed AI to:** Generate the Flask app structure (`app.py`), `classify_with_llm()` with Groq JSON mode, audit log helper, and SQLite store — using the detection signals section and architecture diagram from `planning.md`.

**What it produced:** A working Flask skeleton with route stubs and a Groq integration.

**What I revised:** Fixed the LLM system prompt after Groq rejected malformed JSON (unquoted `reasoning` field). Added regex fallback parsing for `ai_likelihood` when JSON mode fails. Split code into separate modules (`signals/`, `store.py`, `audit_log.py`) instead of a single file.

### Instance 2: Stylometric signal and scoring logic (Milestone 4)

**Directed AI to:** Implement `compute_stylometric_score()` and `combine_scores()` / `determine_attribution()` per the spec's weights, thresholds, and disagreement rules.

**What it produced:** The stylometric and scoring modules with weighted blending and three attribution bands.

**What I revised:** Changed variance to standard deviation after benchmark testing showed raw variance misclassified corporate AI text. Added cross-signal conflict detection so lightly edited AI doesn't get labeled `likely_human` when stylometrics and the LLM point in opposite directions. Tuned the LLM prompt to score edited AI drafts in the 0.5–0.7 range.

### Instance 3: Appeals and rate limiting (Milestone 5)

**Directed AI to:** Add `POST /appeal`, Flask-Limiter on `/submit`, and audit log appeal updates per the appeals workflow spec.

**What it produced:** Full appeal endpoint with 404/409 handling, in-memory rate limiter, and audit log fields for `appeal_reasoning` and `appeal_timestamp`.

**What I revised:** Added `Optional` import that was missing in `audit_log.py`. Ensured audit log entries include truncated `text` for reviewer visibility. Confirmed rate limit applies only to `/submit`, not `/appeal`.

---

## Portfolio Walkthrough

Record a 2–3 minute screen recording following this script:

1. **Intro (15 sec)** — "This is Provenance Guard, a backend that classifies whether creative text is human-written or AI-generated."
2. **Submit human text (30 sec)** — `curl POST /submit` with the casual ramen review. Show `confidence: 0.31`, `attribution: likely_human`, and the Human-Written label.
3. **Submit AI text (30 sec)** — `curl POST /submit` with corporate boilerplate. Show higher confidence (~0.70), `attribution: uncertain`, and the Authorship Unclear label. Explain why it's uncertain (signal disagreement protects creators).
4. **Audit log (20 sec)** — `curl GET /log`. Point out both signal scores, timestamp, and structured JSON.
5. **Appeal (20 sec)** — `curl POST /appeal` with a `content_id`. Show status changing to `under_review` in the log with `appeal_reasoning`.
6. **Rate limit (15 sec)** — Show the 429 output from rapid-fire requests.
7. **Design decisions (20 sec)** — Mention two-signal pipeline, asymmetric thresholds, and appeals path.

Upload the recording to the course portal alongside this repo link.
