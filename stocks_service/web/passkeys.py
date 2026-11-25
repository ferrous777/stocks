"""Passkey (WebAuthn) sign-in for the website's single owner.

A passkey is added from the Security page while signed in (the first time with the secret sign-in link),
then signs in with Face ID, Touch ID or a device PIN. Only public keys are stored here.

Challenges travel in the signed session cookie, so anonymous visitors cannot make the server write anything.
Each is bound to its purpose, expires after five minutes and works once: a verified challenge is recorded in
``passkey_used_challenges`` under a unique id, so a replay is refused.
"""

from __future__ import annotations

import datetime as dt
import secrets
import time
from typing import Any
from urllib.parse import urlsplit

from pymongo import ASCENDING
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from webauthn import (generate_authentication_options, generate_registration_options, options_to_json,
                      verify_authentication_response, verify_registration_response)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)

RP_NAME = "Stocks"
USER_NAME = "owner"
USER_ID = b"stocks-owner"     # one owner; a constant, so a device replaces rather than duplicates its passkey
CHALLENGE_SECONDS = 300
MAX_NAME = 60
SESSION_KEY = "passkey_challenge"


class PasskeyError(ValueError):
    """The passkey request cannot be accepted; the message is safe to show."""


def rp_id(origin: str) -> str:
    return urlsplit(origin).hostname or ""


def list_passkeys(db: Database) -> list[dict]:
    return list(db.passkeys.find().sort("created_at", ASCENDING))


def has_passkeys(db: Database) -> bool:
    return db.passkeys.find_one({}, {"_id": 1}) is not None


def exists(db: Database, credential_id: str) -> bool:
    return db.passkeys.find_one({"_id": credential_id}, {"_id": 1}) is not None


def delete(db: Database, credential_id: str) -> bool:
    return db.passkeys.delete_one({"_id": credential_id}).deleted_count == 1


# --- challenges -------------------------------------------------------------------------------

def _issue_challenge(session: dict, purpose: str) -> bytes:
    challenge = secrets.token_bytes(32)
    session[SESSION_KEY] = {"c": bytes_to_base64url(challenge), "p": purpose, "t": int(time.time())}
    return challenge


def _take_challenge(session: dict, purpose: str) -> bytes:
    pending = session.pop(SESSION_KEY, None)
    if not pending or pending.get("p") != purpose:
        raise PasskeyError("No passkey request in progress; try again.")
    if not 0 <= time.time() - pending["t"] <= CHALLENGE_SECONDS:
        raise PasskeyError("The passkey request expired; try again.")
    return base64url_to_bytes(pending["c"])


def _spend_challenge(db: Database, challenge: bytes, now: dt.datetime) -> None:
    """Called only after the signature verified, so nobody without a passkey can write here."""
    try:
        db.passkey_used_challenges.insert_one({
            "_id": bytes_to_base64url(challenge),
            "expires_at": now + dt.timedelta(seconds=2 * CHALLENGE_SECONDS)})
    except DuplicateKeyError:
        raise PasskeyError("This passkey response was already used; try again.") from None


# --- adding a passkey (signed in) -------------------------------------------------------------

def registration_options(db: Database, session: dict, origin: str) -> str:
    return options_to_json(generate_registration_options(
        rp_id=rp_id(origin), rp_name=RP_NAME, user_id=USER_ID, user_name=USER_NAME, user_display_name=RP_NAME,
        challenge=_issue_challenge(session, "register"),
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,          # usable without typing a username
            user_verification=UserVerificationRequirement.REQUIRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(p["_id"]))
                             for p in list_passkeys(db)]))


def register(db: Database, session: dict, origin: str, *, credential: Any, name: str, now: dt.datetime) -> str:
    challenge = _take_challenge(session, "register")
    name = " ".join(name.split()) if isinstance(name, str) else ""
    if not 1 <= len(name) <= MAX_NAME:
        raise PasskeyError(f"Give the passkey a name of 1 to {MAX_NAME} characters.")
    try:
        v = verify_registration_response(credential=credential, expected_challenge=challenge,
                                         expected_rp_id=rp_id(origin), expected_origin=origin,
                                         require_user_verification=True)
    except (WebAuthnException, ValueError, TypeError, KeyError, AttributeError) as e:
        raise PasskeyError("The passkey could not be verified; it was not added.") from e
    _spend_challenge(db, challenge, now)
    credential_id = bytes_to_base64url(v.credential_id)
    try:
        db.passkeys.insert_one({
            "_id": credential_id, "name": name, "public_key": bytes_to_base64url(v.credential_public_key),
            "sign_count": v.sign_count, "synced": v.credential_backed_up, "rp_id": rp_id(origin),
            "created_at": now, "last_used_at": None})
    except DuplicateKeyError:
        raise PasskeyError("This passkey is already added.") from None
    return credential_id


# --- signing in -------------------------------------------------------------------------------

def authentication_options(session: dict, origin: str) -> str:
    # No credential list: the device offers its own passkeys for this site and nothing is disclosed.
    return options_to_json(generate_authentication_options(
        rp_id=rp_id(origin), challenge=_issue_challenge(session, "login"),
        user_verification=UserVerificationRequirement.REQUIRED))


def authenticate(db: Database, session: dict, origin: str, *, credential: Any, now: dt.datetime) -> str:
    """The credential id that signed in; raises PasskeyError otherwise."""
    challenge = _take_challenge(session, "login")
    credential_id = credential.get("id") if isinstance(credential, dict) else None
    stored = db.passkeys.find_one({"_id": credential_id}) if isinstance(credential_id, str) else None
    if stored is None:
        raise PasskeyError("That passkey is not registered for this site.")
    try:
        v = verify_authentication_response(
            credential=credential, expected_challenge=challenge, expected_rp_id=rp_id(origin),
            expected_origin=origin, credential_public_key=base64url_to_bytes(stored["public_key"]),
            credential_current_sign_count=stored["sign_count"], require_user_verification=True)
    except (WebAuthnException, ValueError, TypeError, KeyError, AttributeError) as e:
        raise PasskeyError("The passkey could not be verified.") from e
    _spend_challenge(db, challenge, now)
    if not db.passkeys.update_one({"_id": credential_id}, {"$set": {
            "sign_count": v.new_sign_count, "synced": v.credential_backed_up, "last_used_at": now}}).matched_count:
        raise PasskeyError("That passkey is not registered for this site.")   # removed meanwhile
    return credential_id
