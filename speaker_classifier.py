"""
Speaker Role Classifier.
Determines which speakers are 'Customer' vs 'Placement' (internal staff)
using multiple heuristics.
"""

import logging
from config import Config

logger = logging.getLogger(__name__)


class SpeakerClassifier:
    """Classifies speakers into Customer or Placement roles."""

    def __init__(self, company_domains: list = None, db=None):
        self.company_domains = company_domains or Config.COMPANY_DOMAINS
        self.db = db

    def classify(self, transcript_data: dict) -> dict:
        """
        Classify all speakers in a transcript.

        Returns:
            Dict[speaker_name, {"role": "Customer"|"Placement", "confidence": float, "method": str}]
        """
        speakers = transcript_data.get("speakers", [])
        attendees = transcript_data.get("meeting_attendees", [])
        organizer_email = transcript_data.get("organizer_email", "")
        participants = transcript_data.get("participants", [])
        sentences = transcript_data.get("sentences", [])
        transcript_id = transcript_data.get("id", "")

        # Get all unique speaker names from sentences
        speaker_names = set()
        for s in sentences:
            name = s.get("speaker_name", "").strip()
            if name:
                speaker_names.add(name)

        # Also add from speakers list
        for s in speakers:
            name = s.get("name", "").strip()
            if name:
                speaker_names.add(name)

        # Build email-to-name mapping from attendees
        email_to_name = {}
        name_to_email = {}
        for att in attendees:
            email = (att.get("email") or "").strip().lower()
            name = (att.get("displayName") or "").strip()
            if email and name:
                email_to_name[email] = name
                name_to_email[name.lower()] = email

        classifications = {}

        for speaker_name in speaker_names:
            role, confidence, method = self._classify_speaker(
                speaker_name=speaker_name,
                organizer_email=organizer_email,
                participants=participants,
                name_to_email=name_to_email,
                email_to_name=email_to_name,
                transcript_id=transcript_id,
            )
            classifications[speaker_name] = {
                "role": role,
                "confidence": confidence,
                "method": method,
            }

        # Log results
        for name, info in classifications.items():
            logger.debug(
                f"Speaker '{name}' classified as {info['role']} "
                f"(confidence: {info['confidence']:.0%}, method: {info['method']})"
            )

        return classifications

    def _classify_speaker(
        self,
        speaker_name: str,
        organizer_email: str,
        participants: list,
        name_to_email: dict,
        email_to_name: dict,
        transcript_id: str,
    ) -> tuple:
        """
        Classify a single speaker using a hierarchy of methods.

        Returns: (role, confidence, method)
        """

        # Method 1: Check manual overrides from database (highest priority)
        if self.db:
            manual_roles = self.db.get_speaker_roles(transcript_id)
            if speaker_name in manual_roles:
                return manual_roles[speaker_name], 1.0, "manual_override"

        # Method 2: Email domain matching
        speaker_email = name_to_email.get(speaker_name.lower(), "")
        if speaker_email and self.company_domains:
            domain = speaker_email.split("@")[-1].lower() if "@" in speaker_email else ""
            if domain:
                if domain in [d.lower() for d in self.company_domains]:
                    return "Placement", 0.95, "email_domain"
                else:
                    return "Customer", 0.90, "email_domain"

        # Method 3: Match against participants list
        if participants and self.company_domains:
            for participant_email in participants:
                p_email = participant_email.strip().lower()
                p_domain = p_email.split("@")[-1] if "@" in p_email else ""

                # Try to match participant to speaker by name similarity
                p_name = email_to_name.get(p_email, "")
                if p_name and self._names_match(speaker_name, p_name):
                    if p_domain in [d.lower() for d in self.company_domains]:
                        return "Placement", 0.85, "participant_email"
                    else:
                        return "Customer", 0.80, "participant_email"

        # Method 4: Organizer is typically internal (Placement)
        if organizer_email:
            organizer_name = email_to_name.get(organizer_email.strip().lower(), "")
            if organizer_name and self._names_match(speaker_name, organizer_name):
                return "Placement", 0.70, "organizer_match"

            # Organizer domain check
            org_domain = organizer_email.split("@")[-1].lower() if "@" in organizer_email else ""
            if org_domain and self.company_domains:
                if org_domain in [d.lower() for d in self.company_domains]:
                    # Organizer is internal — if this speaker's name is very different, likely customer
                    pass  # Not enough info to decide

        # Method 5: If only 2 speakers, and one is identified, the other is opposite
        # (This gets resolved in a post-processing step)

        # Method 6: Name-based heuristics
        if self.company_domains:
            lower_name = speaker_name.lower()
            for domain in self.company_domains:
                company_name = domain.split(".")[0].lower()
                if company_name in lower_name:
                    return "Placement", 0.60, "name_heuristic"

        # Default: Unknown → treat as Customer (safer to flag than miss)
        return "Customer", 0.30, "default"

    def _names_match(self, name1: str, name2: str) -> bool:
        """Check if two names likely refer to the same person."""
        n1 = name1.strip().lower()
        n2 = name2.strip().lower()

        # Exact match
        if n1 == n2:
            return True

        # One contains the other
        if n1 in n2 or n2 in n1:
            return True

        # First name match
        n1_parts = n1.split()
        n2_parts = n2.split()
        if n1_parts and n2_parts and n1_parts[0] == n2_parts[0]:
            return True

        return False

    def post_process_classifications(self, classifications: dict) -> dict:
        """
        Post-process: if only 2 speakers and one is classified with high confidence,
        assign the other the opposite role.
        """
        if len(classifications) == 2:
            names = list(classifications.keys())
            c1, c2 = classifications[names[0]], classifications[names[1]]

            # If one is high confidence and other is default/low
            if c1["confidence"] >= 0.70 and c2["confidence"] < 0.50:
                opposite = "Customer" if c1["role"] == "Placement" else "Placement"
                classifications[names[1]] = {
                    "role": opposite,
                    "confidence": 0.65,
                    "method": "inferred_opposite",
                }
            elif c2["confidence"] >= 0.70 and c1["confidence"] < 0.50:
                opposite = "Customer" if c2["role"] == "Placement" else "Placement"
                classifications[names[0]] = {
                    "role": opposite,
                    "confidence": 0.65,
                    "method": "inferred_opposite",
                }

        return classifications
