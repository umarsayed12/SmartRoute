# Machine Learning Routing Architecture

SmartRoute uses a hybrid routing engine that combines rule-based heuristics with a learned, feedback-driven machine learning classifier. This document explains the machine learning implementation in detail: the algorithm chosen, the training lifecycle, feature engineering, multi-tenant isolation, database storage, and operational benefits.

---

## Table of Contents

1. [High-Level Architecture](#high-level-architecture)
2. [Algorithm & Pipeline Design](#algorithm--pipeline-design)
3. [Why Logistic Regression?](#why-logistic-regression)
4. [Feature Extraction (10 Numeric Signals)](#feature-extraction-10-numeric-signals)
5. [Feedback-to-Label Conversion](#feedback-to-label-conversion)
6. [Training & Evaluation Lifecycle](#training--evaluation-lifecycle)
7. [Tenant Isolation: Workspace-Level Training](#tenant-isolation-workspace-level-training)
8. [Persistence & Storage Schema](#persistence--storage-schema)
9. [Runtime Inference Flow](#runtime-inference-flow)
10. [Future Benefits & Performance Impact](#future-benefits--performance-impact)

---

## High-Level Architecture

SmartRoute evaluates incoming chat requests and assigns them to the cheapest viable model tier (`small`, `medium`, or `large`). 

```
                                  Incoming Chat Request
                                            │
                                            ▼
                              ┌───────────────────────────┐
                              │    Extract 10 Features    │
                              └─────────────┬─────────────┘
                                            │
                                            ▼
                             Has Saved Workspace Model?
                                    /               \
                              (Yes)/                 \(No)
                                  ▼                   ▼
                      ┌───────────────────────┐   ┌────────────────────────┐
                      │ Scikit-Learn Pipeline │   │ Static Rule Heuristics │
                      │  (predict_proba)      │   │  (pick_tier)           │
                      └───────────┬───────────┘   └───────────┬────────────┘
                                  │                           │
                                  └─────────────┬─────────────┘
                                                │
                                                ▼
                                   Route to Configured Tier
                                  (`small` / `medium` / `large`)
                                                │
                                                ▼
                                   User Feedback (+1 / -1)
                                                │
                                                ▼
                                    Retrain Router Classifier
```

---

## Algorithm & Pipeline Design

The learner implementation lives in [`backend/app/train.py`](file:///C:/My%20Work%20Local/othe/SmartRoute/backend/app/train.py).

It uses a standard `scikit-learn` pipeline consisting of two stages:
1. **`StandardScaler()`**: Centers and scales each of the 10 extracted numeric features so that features with large ranges (such as `prompt_chars`) do not dominate features with small binary ranges (such as `has_code`).
2. **`LogisticRegression(max_iter=1000)`**: A multinomial logistic regression classifier that outputs calibrated probabilities across the three model tiers (`small`, `medium`, and `large`).

```python
pipeline = Pipeline([
    ("scaler", StandardScaler()),
    ("classifier", LogisticRegression(max_iter=1000)),
])
```

---

## Why Logistic Regression?

Rather than employing a deep neural network or an auxiliary LLM judge, Logistic Regression was selected for several fundamental engineering reasons:

| Requirement | Logistic Regression | LLM / Deep Neural Network |
| :--- | :--- | :--- |
| **Inference Latency** | **< 1 ms** (a simple dot product and softmax) | 200 ms – 1500 ms (adds significant delay to every call) |
| **Training Sample Size** | **30 samples** minimum to fit a reliable model | Hundreds or thousands of samples needed to avoid overfitting |
| **Probability Calibration** | Built-in via `predict_proba()` | Requires temperature scaling or verbalized confidence |
| **Operational Overhead** | In-memory CPU execution, zero external dependencies | Requires GPU compute or extra API token costs |
| **Interpretability** | Linear feature weights are completely inspectable | Black-box weights or prompt drift |

Because the gateway sits directly in the hot path of user application requests, the routing decision must be near-instantaneous and computationally inexpensive.

---

## Feature Extraction (10 Numeric Signals)

Before routing or training, incoming messages are converted into a dense vector of 10 numeric features in [`backend/app/routing/features.py`](file:///C:/My%20Work%20Local/othe/SmartRoute/backend/app/routing/features.py):

| Feature Name | Type | Description |
| :--- | :--- | :--- |
| `prompt_chars` | `float` | Total character count of the latest user message. |
| `prompt_words` | `float` | Total word count of the latest user message. |
| `num_turns` | `float` | Number of previous conversation turns in the chat history. |
| `has_code` | `0.0 / 1.0` | Detected code blocks (` ``` `), keywords (`def`, `class`, `function`, `sql`), or syntax. |
| `has_math` | `0.0 / 1.0` | Detected mathematical formulas, operators, or keywords (`calculate`, `integral`, `equation`). |
| `question_count` | `float` | Count of question marks in the prompt. |
| `asks_reasoning` | `0.0 / 1.0` | Presence of analytical keywords (`explain`, `why`, `compare`, `analyze`, `step-by-step`). |
| `asks_long_output` | `0.0 / 1.0` | Presence of expansive keywords (`detailed`, `essay`, `comprehensive`, `generate a`). |
| `non_ascii_ratio` | `float` | Proportion of non-ASCII characters (detects multilingual prompts or special symbols). |
| `avg_word_len` | `float` | Average length of words (proxy for technical/academic vocabulary complexity). |

Feature extraction is deterministic, regex-based, and completes in microseconds.

---

## Feedback-to-Label Conversion

Supervised training requires ground-truth target labels. SmartRoute derives these labels directly from user feedback (thumbs up / thumbs down) in [`_feedback_label()`](file:///C:/My%20Work%20Local/othe/SmartRoute/backend/app/train.py#L23-L29):

* **Positive Rating (`score = 1`)**:
  The response was accurate and satisfactory.
  $$\text{Target Tier} = \text{tier\_final}$$
  *(The model that answered was sufficient; the router should continue using this tier for similar prompts.)*

* **Negative Rating (`score = -1`)**:
  The response was inaccurate, incomplete, or hallucinated.
  $$\text{Target Tier} = \min(\text{index}(\text{tier\_final}) + 1, \text{len}(\text{tiers}) - 1)$$
  *(The model was insufficient; the router promotes the prompt to a higher tier: `small` $\rightarrow$ `medium`, `medium` $\rightarrow$ `large`.)*

---

## Training & Evaluation Lifecycle

When training is triggered (via `POST /v1/train` or the platform **Settings** page):

1. **Pre-flight Checks**:
   - Training requires at least **30 labelled completed requests** (`n_rows >= 30`).
   - The dataset must contain examples covering at least **two distinct tier labels**.
2. **Train/Test Holdout Split**:
   - If each class has at least two instances, data is split **80% train / 20% test** with stratification.
   - Evaluates test accuracy and builds a confusion matrix on the holdout partition.
3. **Full Dataset Fit**:
   - The model is refitted across 100% of the workspace's labelled examples so all available feedback informs production routing.
4. **Artifact Generation**:
   - The fitted pipeline is serialized using `joblib.dump` into a binary byte buffer.

---

## Tenant Isolation: Workspace-Level Training

Training in SmartRoute is **strictly workspace-scoped (tenant-isolated)**. There is **no global model** shared across users.

### Why Workspace-Level Isolation?

1. **Zero Data Leakage & Absolute Privacy:**
   Workspaces often process confidential company data, proprietary source code, or personal identifiable information (PII). Training a global model on shared signals could leak prompt patterns across organizations.
2. **Bring Your Own Model (BYOM) Heterogeneity:**
   Each workspace configures its own models, providers, and prices:
   - Workspace A might configure `groq/allam-2-7b` (small) and `groq/openai/gpt-oss-120b` (large).
   - Workspace B might configure `openai/gpt-4o-mini` (small) and `anthropic/claude-3-5-sonnet` (large).  
   Because the capabilities, pricing, and performance of tiers differ per tenant, a unified global classifier would produce inaccurate routing.
3. **Application Domain Specialization:**
   A prompt that requires a `large` model in a customer-support setting might be handled easily by a `small` model in a coding assistant with predefined context. Workspace-level training allows the classifier to specialize specifically in that workspace's traffic patterns.

---

## Persistence & Storage Schema

Fitted models are persisted directly in PostgreSQL in the `smartroute.router_models` table (defined in [`backend/app/hosted/schema.py`](file:///C:/My%20Work%20Local/othe/SmartRoute/backend/app/hosted/schema.py#L183-L190)):

```sql
CREATE TABLE smartroute.router_models (
    workspace_id UUID PRIMARY KEY REFERENCES smartroute.workspaces(id) ON DELETE CASCADE,
    artifact BYTEA NOT NULL,
    metadata JSONB NOT NULL,
    feature_order JSONB NOT NULL,
    trained_at TIMESTAMPTZ NOT NULL
);
```

### Fields:
* **`workspace_id`**: The tenant owning the model.
* **`artifact`**: The serialized binary `scikit-learn` pipeline.
* **`metadata`**: Stored training results, including accuracy, confusion matrix, row count, and class names:
  ```json
  {
    "trained": true,
    "trained_at": "2026-10-21T04:42:11.533460+00:00",
    "n_rows": 32,
    "accuracy": 0.857,
    "classes": ["large", "medium", "small"],
    "confusion_matrix": [[1, 0, 0], [0, 2, 1], [0, 0, 3]],
    "evaluation": "holdout"
  }
  ```
* **`feature_order`**: Explicit list of feature names to guarantee that model feature columns remain in exact alignment.

---

## Runtime Inference Flow

When an inference call reaches [`route_and_log()`](file:///C:/My%20Work%20Local/othe/SmartRoute/backend/app/hosted/routing.py#L61-L108):

1. **Feature Extraction**: Features are extracted from the prompt in memory.
2. **Model Lookup**: The gateway checks `smartroute.router_models` for the calling workspace.
3. **Prediction via `_learned()`**:
   - The pipeline is loaded from the binary artifact.
   - It runs `model.predict_proba([[features...]])`.
   - The class with the highest probability is chosen.
   - A reason string is generated: `"Workspace learned policy (probability 0.94)."`.
4. **Fallback Mechanism**:
   - If no model has been trained yet (or if the workspace preference is set to `heuristic_only`), the system seamlessly falls back to static rule-based heuristics ([`pick_tier()`](file:///C:/My%20Work%20Local/othe/SmartRoute/backend/app/routing/heuristic.py)).

---

## Future Benefits & Performance Impact

* **Adaptive Optimization**: As traffic volume and user feedback grow, the model learns subtle boundaries that static rules cannot capture (e.g., distinguishing between simple coding snippets and complex architectural queries).
* **Minimized Escalations**: Heuristic routing often escalates conservatively to expensive models. The ML router predicts the correct tier on the first attempt, saving latency and escalation costs.
* **Seamless Provider Swapping**: If a workspace changes its configured models (e.g., upgrading a `medium` tier model), human feedback on new responses recalibrates the router without rewriting software rules.
* **Quantifiable Quality Tracking**: The confusion matrix and holdout accuracy provide measurable confidence metrics on how well the gateway routes queries for that tenant.
