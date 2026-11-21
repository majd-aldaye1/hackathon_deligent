"""The optional language-model fallback, over the OpenRouter API.

The brief allows a model "only via the OpenRouter API, key in env var
OPENROUTER_API_KEY", and requires the system to run regex-only when the key is missing or
the API fails.  So everything here is a best effort that returns None on any problem, and
nothing here decides anything: the model only reads free text, and a fact it recovers is
marked **provisional** (decision log D28) so it can block a clear but never carry one.

Every answer must be grounded: the model returns the verbatim span it read the fact from,
this module checks the span really is in the source text, and checks the value it claims
really is in the span.  Anything that fails those checks becomes "unknown".
"""

import hashlib
import json
import os
import re
import threading
import urllib.error
import urllib.request

from . import countries, dates, norm

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
ENV_KEY = "OPENROUTER_API_KEY"
ENV_MODEL = "OPENROUTER_MODEL"
DEFAULT_MODEL = "openai/gpt-4o-mini"

# Bumped whenever a prompt changes, so a cache entry can never outlive its prompt.
PROMPT_VERSION = "2"

TIMEOUT_SECONDS = 20
MAX_ATTEMPTS = 2
MAX_TEXT = 4000


def api_key(env=None):
    """The key, from the one environment variable the brief names and nowhere else.

    Deliberately not read from a file: the system's behaviour should depend on the folder
    it was given and the environment it was run in, not on an untracked file that happens
    to sit beside the code.  `key_from_dotenv` exists for the development tools.
    """
    env = os.environ if env is None else env
    return (env.get(ENV_KEY) or "").strip()


def key_from_dotenv(path=None):
    """A key from a .env file, for the development tools only."""
    return _key_from_dotenv(path)


def _key_from_dotenv(path=None):
    if path is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, ".env")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = re.match(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
                if not match:
                    continue
                name, value = match.group(1), match.group(2).strip().strip("\"'")
                if name.lower() in ("openrouter_api_key", "open_router_key", "openrouter_key"):
                    return value
    except OSError:
        return ""
    return ""


class Usage(object):
    """What the run cost, for the README."""

    def __init__(self):
        self.calls = 0
        self.failures = 0
        self.cache_hits = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.seconds = 0.0
        self._lock = threading.Lock()

    def record(self, prompt_tokens=0, completion_tokens=0, seconds=0.0, failed=False):
        with self._lock:
            self.calls += 1
            if failed:
                self.failures += 1
            self.prompt_tokens += prompt_tokens
            self.completion_tokens += completion_tokens
            self.seconds += seconds

    def hit(self):
        with self._lock:
            self.cache_hits += 1

    def summary(self):
        return {
            "calls": self.calls,
            "failures": self.failures,
            "cache_hits": self.cache_hits,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "seconds": round(self.seconds, 1),
        }

    def __repr__(self):
        return "Usage(%r)" % self.summary()


class Client(object):
    """One model behind one HTTP endpoint, with a cache, a timeout and a retry."""

    def __init__(self, key=None, model=None, timeout=TIMEOUT_SECONDS,
                 attempts=MAX_ATTEMPTS, opener=None):
        self.key = key if key is not None else api_key()
        self.model = model or os.environ.get(ENV_MODEL) or DEFAULT_MODEL
        self.timeout = timeout
        self.attempts = attempts
        self.usage = Usage()
        self._cache = {}
        self._lock = threading.Lock()
        # Injectable so the tests can exercise every path without a network.
        self._opener = opener or self._post

    @property
    def available(self):
        return bool(self.key)

    def ask(self, system_prompt, user_text):
        """A JSON object from the model, or None.

        Cached on the exact prompt and text, so a run never asks the same question twice
        and a single run is self-consistent.
        """
        if not self.available:
            return None
        key = hashlib.sha256(
            ("%s\x00%s\x00%s\x00%s" % (PROMPT_VERSION, self.model, system_prompt, user_text))
            .encode("utf-8")
        ).hexdigest()
        with self._lock:
            if key in self._cache:
                self.usage.hit()
                return self._cache[key]
        answer = self._ask_uncached(system_prompt, user_text)
        with self._lock:
            self._cache[key] = answer
        return answer

    def _ask_uncached(self, system_prompt, user_text):
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text[:MAX_TEXT]},
            ],
            # Deterministic as far as the API allows: no sampling, a fixed seed, and a
            # response that has to be JSON.
            "temperature": 0,
            "top_p": 1,
            "seed": 7,
            "max_tokens": 400,
            "response_format": {"type": "json_object"},
        }
        for attempt in range(self.attempts):
            parsed = self._opener(body)
            if parsed is not None:
                return parsed
        return None

    def _post(self, body):
        import time

        started = time.time()
        request = urllib.request.Request(
            ENDPOINT,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": "Bearer %s" % self.key,
                "Content-Type": "application/json",
                "X-Title": "same-person-or-not",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError,
                json.JSONDecodeError):
            self.usage.record(seconds=time.time() - started, failed=True)
            return None
        usage = payload.get("usage") or {}
        self.usage.record(
            prompt_tokens=usage.get("prompt_tokens", 0) or 0,
            completion_tokens=usage.get("completion_tokens", 0) or 0,
            seconds=time.time() - started,
        )
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
        return _loads(content)


def _loads(content):
    """The model's content as an object, tolerating a code fence around it."""
    if not isinstance(content, str):
        return None
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"```\s*$", "", text).strip()
    try:
        parsed = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


# ------------------------------------------------------------------------ grounding


def quote_is_verbatim(quote, text):
    """The span the model cites has to be in the source, character for character.

    Whitespace is allowed to differ, because models reflow long text.
    """
    if not quote or not text or not isinstance(quote, str):
        return False
    if quote in text:
        return True
    squeeze = lambda s: re.sub(r"\s+", " ", s).strip()
    return squeeze(quote) in squeeze(text)


def _digits_present(value, quote):
    """Is this number written in the span as a number in its own right?

    A plain substring test is not enough: "3" is inside "1939", which would let a model
    claim March from a span that only says 1939.
    """
    return bool(re.search(r"(?<!\d)0*%d(?!\d)" % int(value), re.sub(r"\s+", " ", quote)))


def _month_present(month, quote):
    if not month:
        return True
    name = dates.MONTH_NAMES[month - 1].lower()
    folded = norm.fold(quote)
    if name in folded or re.search(r"\b%s\b" % name[:3], folded):
        return True
    return _digits_present(month, quote)


def grounded_date(quote, text, value):
    """A date the model claims, only if the cited span really states it.

    The year has to be in the span, and the month has to be identifiable in it as digits
    or as a month name.  The day is not required, because the span may write it as a word
    ("the twelfth of May 1966") and because a provisional date can only ever block a
    clear, never carry one — so a day read one off cannot cause the costly mistake.
    """
    if not quote_is_verbatim(quote, text):
        return None
    parsed = dates.parse(value)
    if parsed is None:
        return None
    if not _digits_present(parsed.year, quote):
        return None
    if not _month_present(parsed.month, quote):
        return None
    return parsed


def grounded_years_from_age(quote, text, age, as_of_year):
    """The two birth years an age against a year allows.

    The age has to be inside the cited span, because that is the fact being read.  The
    year only has to be somewhere in the source text: a model that cites "24 years of age"
    is quoting the age correctly even though the year sits earlier in the sentence.
    Neither number can be invented, which is what grounding is for.
    """
    if not quote_is_verbatim(quote, text):
        return []
    try:
        age = int(age)
        as_of_year = int(as_of_year)
    except (TypeError, ValueError):
        return []
    if not 0 < age < 120 or not 1000 < as_of_year < 3000:
        return []
    if not _digits_present(age, quote):
        return []
    if not _digits_present(as_of_year, text):
        return []
    return sorted({as_of_year - age, as_of_year - age - 1})


def grounded_country(quote, text, value):
    """A country the model claims, only if the words are inside the cited span."""
    if not quote_is_verbatim(quote, text) or not isinstance(value, str):
        return None
    key = countries.key(value)
    if key is None or key not in countries.KNOWN_NAMES:
        # The table's identity fallback lets an unmapped spelling stand for itself, which
        # is right for a structured field and wrong for a model's free-text reading: a
        # country we do not know is a country we cannot compare.
        return None
    folded = norm.fold(quote)
    if norm.fold(value) in folded:
        return key
    # The span may carry the adjective ("Brazilian") while the value is the country.
    return key if countries.mentioned_in(quote, keys={key}) else None


def grounded_name(quote, text, value):
    """A name the model claims, only if its words are inside the cited span."""
    if not quote_is_verbatim(quote, text) or not isinstance(value, str):
        return None
    words = norm.words(value)
    if not words:
        return None
    folded = set(norm.words(quote))
    return value.strip() if all(w in folded for w in words) else None


def build(key=None, model=None):
    """A client, or None when there is no key to use."""
    client = Client(key=key, model=model)
    return client if client.available else None


# ------------------------------------------------------------------------- prompts

_RULES = (
    "Answer with a single JSON object and nothing else. "
    "Quote spans must be copied character for character from the text you were given; "
    "never paraphrase, correct or complete them. "
    "If the text does not state the fact, say so rather than inferring it."
)

HIT_BIRTH_PROMPT = (
    "You are reading the opening paragraph of a watchlist profile about one person. "
    "Report a date of birth only if the paragraph states one outright, or states the "
    "person's age at a stated month or year. Do not infer an age from an event, a "
    "sentence length, a quantity or a sum of money.\n"
    'Return {"found": true|false, "quote": "<verbatim span>", '
    '"birth_date": "<YYYY-MM-DD or YYYY, or null>", "age": <number or null>, '
    '"as_of_year": <4-digit year or null>}.\n'
    "Use birth_date when the paragraph states a birth. Use age with as_of_year when it "
    "states an age at a date. The quote must contain the numbers you report.\n" + _RULES
)

NOTE_PLACES_PROMPT = (
    "You are reading one note from a bank's support system about one customer. "
    "Report every country the note says the customer lived, resided, worked or was based "
    "in. Do not report a country that is only the destination of a payment, the issuer of "
    "a document, or the subject of a question.\n"
    'Return {"found": true|false, "items": [{"quote": "<verbatim span>", '
    '"country": "<country name>"}]}.\n'
    "Each quote must contain the country it names.\n" + _RULES
)

NOTE_CHECK_PROMPT = (
    "You are reading one note from a bank's onboarding system that may record an identity "
    "check on one customer. Report the name on the document, the holder's date of birth, "
    "the country that issued the document, and whether the check passed.\n"
    'Return {"found": true|false, "approved": true|false|null, '
    '"name": "<name or null>", "name_quote": "<verbatim span or null>", '
    '"dob": "<YYYY-MM-DD if you can tell, otherwise exactly as written, or null>", '
    '"dob_quote": "<verbatim span or null>", '
    '"country": "<country or null>", "country_quote": "<verbatim span or null>"}.\n'
    "The date of birth is the holder's, never the date the check was run. Set approved to "
    "false if the note records a refusal, an expiry or a failure.\n" + _RULES
)


class BirthFromText(object):
    __slots__ = ("dates", "quote")

    def __init__(self, dates_, quote):
        self.dates = list(dates_)
        self.quote = quote


class PlaceFromText(object):
    __slots__ = ("country", "quote")

    def __init__(self, country, quote):
        self.country = country
        self.quote = quote


class CheckFromText(object):
    __slots__ = ("name", "dob", "country", "approved", "quotes")

    def __init__(self, name=None, dob=None, country=None, approved=None, quotes=None):
        self.name = name
        self.dob = dob
        self.country = country
        self.approved = approved
        self.quotes = dict(quotes or {})

    @property
    def is_approved(self):
        return self.approved is True

    @property
    def empty(self):
        return self.name is None and self.dob is None and self.country is None


class Extractor(object):
    """The three jobs the model is allowed to do, each grounded in a verbatim span."""

    def __init__(self, client):
        self.client = client

    @property
    def usage(self):
        return self.client.usage

    @property
    def model(self):
        return self.client.model

    def hit_birth(self, text):
        """A date of birth from a hit's opening paragraph, or None."""
        answer = self.client.ask(HIT_BIRTH_PROMPT, text)
        if not answer or not answer.get("found"):
            return None
        quote = answer.get("quote")
        if answer.get("birth_date"):
            parsed = grounded_date(quote, text, answer["birth_date"])
            if parsed is not None:
                return BirthFromText([parsed], quote)
        years = grounded_years_from_age(quote, text, answer.get("age"), answer.get("as_of_year"))
        if years:
            return BirthFromText([dates.Date(y) for y in years], quote)
        return None

    def note_places(self, text):
        """Countries a support note says the customer lived in."""
        answer = self.client.ask(NOTE_PLACES_PROMPT, text)
        if not answer or not answer.get("found"):
            return []
        found, seen = [], set()
        for item in answer.get("items") or []:
            if not isinstance(item, dict):
                continue
            key = grounded_country(item.get("quote"), text, item.get("country"))
            if key and key not in seen:
                seen.add(key)
                found.append(PlaceFromText(key, item.get("quote")))
        return found

    def note_check(self, text):
        """An identity check written up in a note."""
        answer = self.client.ask(NOTE_CHECK_PROMPT, text)
        if not answer or not answer.get("found"):
            return None
        quotes = {}
        name = grounded_name(answer.get("name_quote"), text, answer.get("name"))
        if name:
            quotes["verified_name"] = answer.get("name_quote")
        dob = grounded_date(answer.get("dob_quote"), text, answer.get("dob"))
        if dob is not None:
            quotes["verified_dob"] = answer.get("dob_quote")
        country = grounded_country(answer.get("country_quote"), text, answer.get("country"))
        if country:
            quotes["document_country"] = answer.get("country_quote")
        approved = answer.get("approved")
        if approved not in (True, False):
            approved = None
        check = CheckFromText(name, dob, country, approved, quotes)
        return None if check.empty else check
