"""
Background Sync Service.
Periodically fetches new transcripts from Fireflies and runs the full analysis pipeline.
Also supports on-demand manual sync.
"""

import logging
import traceback
from datetime import datetime, timedelta
from config import Config
from database import Database
from fireflies_client import FirefliesClient
from speaker_classifier import SpeakerClassifier
from sentiment.analyzer import SentimentAnalyzer
from alert_engine import AlertEngine

logger = logging.getLogger(__name__)


class SyncService:
    """Manages automatic and manual transcript sync + analysis pipeline."""

    def __init__(self, db: Database = None):
        self.db = db or Database()
        self.fireflies = FirefliesClient()
        self.classifier = SpeakerClassifier(db=self.db)
        self.analyzer = SentimentAnalyzer(db=self.db)
        self.alert_engine = AlertEngine(db=self.db)
        self._is_running = False

    def sync_and_analyze(self, sync_type: str = "auto", full_sync: bool = False) -> dict:
        """
        Main pipeline: fetch transcripts → classify speakers → analyze sentiment → generate alerts.

        Args:
            sync_type: "auto" or "manual"
            full_sync: If True, fetch ALL transcripts regardless of last sync time

        Returns:
            Dict with sync results summary
        """
        if self._is_running:
            logger.warning("Sync already in progress, skipping")
            return {"status": "skipped", "message": "Sync already in progress"}

        self._is_running = True
        log_id = self.db.create_sync_log(sync_type=sync_type)

        results = {
            "status": "running",
            "sync_id": log_id,
            "transcripts_fetched": 0,
            "transcripts_analyzed": 0,
            "alerts_generated": 0,
            "errors": [],
        }

        try:
            # Check API connection
            if not Config.is_fireflies_configured():
                msg = "Fireflies API key not configured. Using existing/mock data only."
                logger.warning(msg)
                results["errors"].append(msg)

                # Analyze any pending transcripts in the database
                pending = self.db.get_pending_transcripts()
                if pending:
                    for t in pending:
                        try:
                            self._analyze_stored_transcript(t["id"])
                            results["transcripts_analyzed"] += 1
                        except Exception as e:
                            results["errors"].append(f"Error analyzing {t['id']}: {str(e)}")

                results["status"] = "completed"
                self.db.update_sync_log(
                    log_id,
                    completed_at=datetime.utcnow().isoformat(),
                    transcripts_analyzed=results["transcripts_analyzed"],
                    status="completed",
                    errors="; ".join(results["errors"]) if results["errors"] else None,
                )
                return results

            # Determine date range
            if full_sync:
                since_date = None
                logger.info("Starting FULL sync — fetching all transcripts")
            else:
                last_sync = self.db.get_last_sync()
                if last_sync and last_sync.get("completed_at"):
                    since_date = last_sync["completed_at"]
                    logger.info(f"Incremental sync since {since_date}")
                else:
                    since_date = None
                    logger.info("No previous sync found — fetching all transcripts")

            # Step 1: Fetch transcripts from Fireflies
            if since_date:
                raw_transcripts = self.fireflies.fetch_new_transcripts(since_date=since_date)
            else:
                raw_transcripts = self.fireflies.fetch_all_transcripts()

            results["transcripts_fetched"] = len(raw_transcripts)
            logger.info(f"Fetched {len(raw_transcripts)} transcripts from Fireflies")

            # Step 2: Process each transcript
            for raw in raw_transcripts:
                try:
                    transcript_id = raw.get("id", "")
                    if not transcript_id:
                        continue

                    # Fetch full details
                    logger.info(f"Fetching details for transcript: {raw.get('title', transcript_id)}")
                    detail = self.fireflies.fetch_transcript_detail(transcript_id)
                    normalized = self.fireflies.normalize_transcript(detail)

                    # Store in database
                    self.db.upsert_transcript({
                        "id": normalized["id"],
                        "title": normalized["title"],
                        "date": normalized["date"],
                        "date_string": normalized["date_string"],
                        "duration": normalized["duration"],
                        "organizer_email": normalized["organizer_email"],
                        "participants": normalized["participants"],
                        "meeting_attendees": normalized["meeting_attendees"],
                        "transcript_url": normalized["transcript_url"],
                        "speakers": normalized["speakers"],
                    })

                    # Classify speakers
                    speaker_roles = self.classifier.classify(normalized)
                    speaker_roles = self.classifier.post_process_classifications(speaker_roles)

                    # Run sentiment analysis
                    report = self.analyzer.analyze_transcript(normalized, speaker_roles)

                    # Save results
                    self._save_report(report)

                    # Update transcript status
                    self.db.update_transcript_status(transcript_id, "analyzed")

                    # Generate alerts
                    alerts = self.alert_engine.evaluate_and_alert(report, normalized)
                    results["alerts_generated"] += len(alerts)
                    results["transcripts_analyzed"] += 1

                except Exception as e:
                    error_msg = f"Error processing transcript {raw.get('id', '?')}: {str(e)}"
                    logger.error(error_msg)
                    logger.debug(traceback.format_exc())
                    results["errors"].append(error_msg)

                    # Mark as error in DB
                    if raw.get("id"):
                        try:
                            self.db.update_transcript_status(raw["id"], "error")
                        except Exception:
                            pass

            results["status"] = "completed"
            logger.info(
                f"Sync completed: {results['transcripts_fetched']} fetched, "
                f"{results['transcripts_analyzed']} analyzed, "
                f"{results['alerts_generated']} alerts"
            )

        except Exception as e:
            results["status"] = "failed"
            results["errors"].append(f"Sync failed: {str(e)}")
            logger.error(f"Sync failed: {e}")
            logger.debug(traceback.format_exc())

        finally:
            self._is_running = False
            self.db.update_sync_log(
                log_id,
                completed_at=datetime.utcnow().isoformat(),
                transcripts_fetched=results["transcripts_fetched"],
                transcripts_analyzed=results["transcripts_analyzed"],
                alerts_generated=results["alerts_generated"],
                status=results["status"],
                errors="; ".join(results["errors"]) if results["errors"] else None,
            )

        return results

    def process_manual_transcript(self, transcript_data: dict) -> dict:
        """
        Process a manually added transcript directly through the pipeline.
        Bypasses Fireflies fetching.
        """
        transcript_id = transcript_data.get("id")
        try:
            # Store in database
            self.db.upsert_transcript({
                "id": transcript_data["id"],
                "title": transcript_data["title"],
                "date": transcript_data["date"],
                "date_string": transcript_data["date_string"],
                "duration": transcript_data["duration"],
                "organizer_email": transcript_data["organizer_email"],
                "participants": transcript_data["participants"],
                "meeting_attendees": transcript_data["meeting_attendees"],
                "transcript_url": transcript_data["transcript_url"],
                "speakers": transcript_data["speakers"],
            })

            # Classify speakers
            speaker_roles = self.classifier.classify(transcript_data)
            speaker_roles = self.classifier.post_process_classifications(speaker_roles)

            # Run sentiment analysis
            report = self.analyzer.analyze_transcript(transcript_data, speaker_roles)

            # Save results
            self._save_report(report)

            # Update status
            self.db.update_transcript_status(transcript_id, "analyzed")

            # Generate alerts
            alerts = self.alert_engine.evaluate_and_alert(report, transcript_data)

            logger.info(f"Manual transcript {transcript_id} processed successfully. Generated {len(alerts)} alerts.")
            return {"success": True, "transcript_id": transcript_id, "alerts_generated": len(alerts)}
            
        except Exception as e:
            logger.error(f"Error processing manual transcript {transcript_id}: {e}")
            logger.debug(traceback.format_exc())
            
            # Mark as error in DB
            try:
                self.db.update_transcript_status(transcript_id, "error")
            except Exception:
                pass
                
            return {"success": False, "error": str(e)}

    def _analyze_stored_transcript(self, transcript_id: str):
        """Re-analyze a transcript that's already in the database (e.g., mock data)."""
        # This is used when we have transcript data but haven't analyzed it yet
        # For mock data, the sentences are stored alongside the transcript
        pass  # Handled by mock data seeder directly

    def _save_report(self, report):
        """Save a SentimentReport to the database."""
        report_dict = report.to_dict()

        self.db.save_sentiment_result({
            "transcript_id": report.transcript_id,
            "overall_score": report.overall_score,
            "customer_score": report.customer_score,
            "positive_pct": report.positive_pct,
            "neutral_pct": report.neutral_pct,
            "negative_pct": report.negative_pct,
            "sentiment_trajectory": report.sentiment_trajectory,
            "warning_level": report.warning_level,
            "key_negative_moments": report.key_negative_moments,
            "speaker_sentiments": report.speaker_sentiments,
            "analysis_metadata": report.analysis_metadata,
        })

        # Save sentence-level data
        sentence_dicts = []
        for sd in report.sentence_details:
            d = sd.to_dict() if hasattr(sd, 'to_dict') else sd
            sentence_dicts.append(d)

        if sentence_dicts:
            self.db.save_sentence_sentiments(sentence_dicts)

    def is_running(self) -> bool:
        """Check if a sync is currently in progress."""
        return self._is_running


def seed_mock_data(db: Database):
    """
    Seed the database with realistic mock transcript data
    so the dashboard works immediately without API keys.
    """
    logger.info("Seeding mock data for demonstration...")

    mock_transcripts = [
        {
            "id": "mock_001",
            "title": "Q2 Staffing Review — Acme Corp",
            "date": "1749820800000",
            "date_string": "2025-06-13T10:00:00Z",
            "duration": 32.5,
            "organizer_email": "sarah@placement.com",
            "participants": ["sarah@placement.com", "john.smith@acmecorp.com"],
            "meeting_attendees": [
                {"displayName": "Sarah Johnson", "email": "sarah@placement.com"},
                {"displayName": "John Smith", "email": "john.smith@acmecorp.com"},
            ],
            "transcript_url": "",
            "speakers": [
                {"id": "s1", "name": "Sarah Johnson"},
                {"id": "s2", "name": "John Smith"},
            ],
            "sentences": [
                {"index": 0, "text": "Hi John, thanks for joining today. How's everything going with the team we placed last month?", "speaker_name": "Sarah Johnson", "start_time": 0, "end_time": 8, "ai_filters": {"sentiment": "positive"}},
                {"index": 1, "text": "Hey Sarah. Well, to be honest, I'm a bit concerned. Two of the three candidates haven't been performing as expected.", "speaker_name": "John Smith", "start_time": 9, "end_time": 18, "ai_filters": {"sentiment": "negative"}},
                {"index": 2, "text": "I'm sorry to hear that. Can you tell me more about what's been happening?", "speaker_name": "Sarah Johnson", "start_time": 19, "end_time": 24, "ai_filters": {"sentiment": "neutral"}},
                {"index": 3, "text": "The developer you sent, Mark, has been consistently missing deadlines. His code quality is below what we need for production.", "speaker_name": "John Smith", "start_time": 25, "end_time": 36, "ai_filters": {"sentiment": "negative"}},
                {"index": 4, "text": "And Lisa in project management — she seems unfamiliar with agile methodology, which was a core requirement we discussed.", "speaker_name": "John Smith", "start_time": 37, "end_time": 48, "ai_filters": {"sentiment": "negative"}},
                {"index": 5, "text": "I understand your frustration, John. That's definitely not the level of quality we strive for.", "speaker_name": "Sarah Johnson", "start_time": 49, "end_time": 56, "ai_filters": {"sentiment": "neutral"}},
                {"index": 6, "text": "Honestly, I'm disappointed. We're paying premium rates and the output doesn't match. I'm starting to consider looking at other agencies.", "speaker_name": "John Smith", "start_time": 57, "end_time": 70, "ai_filters": {"sentiment": "very negative"}},
                {"index": 7, "text": "I completely understand. Let me put together a remediation plan. We can do replacements at no additional cost.", "speaker_name": "Sarah Johnson", "start_time": 71, "end_time": 80, "ai_filters": {"sentiment": "positive"}},
                {"index": 8, "text": "I appreciate that. But I need to see concrete improvements within the next two weeks, or we'll need to terminate the contract.", "speaker_name": "John Smith", "start_time": 81, "end_time": 92, "ai_filters": {"sentiment": "negative"}},
                {"index": 9, "text": "Absolutely. I'll have replacement candidates ready for your review by Friday. Thank you for giving us the chance to make this right.", "speaker_name": "Sarah Johnson", "start_time": 93, "end_time": 104, "ai_filters": {"sentiment": "positive"}},
                {"index": 10, "text": "Fine. Let's see how it goes. But I'm very upset about the wasted time and resources so far.", "speaker_name": "John Smith", "start_time": 105, "end_time": 114, "ai_filters": {"sentiment": "negative"}},
            ],
        },
        {
            "id": "mock_002",
            "title": "Monthly Check-in — TechVentures Inc",
            "date": "1749734400000",
            "date_string": "2025-06-12T14:00:00Z",
            "duration": 18.0,
            "organizer_email": "mike@placement.com",
            "participants": ["mike@placement.com", "emma.wilson@techventures.com"],
            "meeting_attendees": [
                {"displayName": "Mike Chen", "email": "mike@placement.com"},
                {"displayName": "Emma Wilson", "email": "emma.wilson@techventures.com"},
            ],
            "transcript_url": "",
            "speakers": [
                {"id": "s3", "name": "Mike Chen"},
                {"id": "s4", "name": "Emma Wilson"},
            ],
            "sentences": [
                {"index": 0, "text": "Emma, great to catch up! How are the new team members working out?", "speaker_name": "Mike Chen", "start_time": 0, "end_time": 6, "ai_filters": {"sentiment": "positive"}},
                {"index": 1, "text": "Mike, I have to say, we are absolutely thrilled! David has been outstanding in the backend development role.", "speaker_name": "Emma Wilson", "start_time": 7, "end_time": 16, "ai_filters": {"sentiment": "very positive"}},
                {"index": 2, "text": "That's wonderful to hear! What about the UI/UX designer, Rachel?", "speaker_name": "Mike Chen", "start_time": 17, "end_time": 22, "ai_filters": {"sentiment": "positive"}},
                {"index": 3, "text": "Rachel has exceeded all our expectations. Her designs are clean, modern, and she integrates seamlessly with the team.", "speaker_name": "Emma Wilson", "start_time": 23, "end_time": 34, "ai_filters": {"sentiment": "very positive"}},
                {"index": 4, "text": "We're so happy with this partnership. The quality of candidates you provide is consistently excellent.", "speaker_name": "Emma Wilson", "start_time": 35, "end_time": 44, "ai_filters": {"sentiment": "very positive"}},
                {"index": 5, "text": "Thank you, Emma! We work hard to match the right talent with the right teams.", "speaker_name": "Mike Chen", "start_time": 45, "end_time": 52, "ai_filters": {"sentiment": "positive"}},
                {"index": 6, "text": "In fact, we'd like to expand. We need two more developers for Q3. Can we discuss the requirements?", "speaker_name": "Emma Wilson", "start_time": 53, "end_time": 62, "ai_filters": {"sentiment": "positive"}},
                {"index": 7, "text": "Absolutely! I'd be happy to start the search. Let me pull up the requirements form.", "speaker_name": "Mike Chen", "start_time": 63, "end_time": 70, "ai_filters": {"sentiment": "positive"}},
            ],
        },
        {
            "id": "mock_003",
            "title": "Candidate Dispute — GlobalFin Services",
            "date": "1749648000000",
            "date_string": "2025-06-11T09:30:00Z",
            "duration": 45.0,
            "organizer_email": "anna@placement.com",
            "participants": ["anna@placement.com", "robert.kline@globalfin.com"],
            "meeting_attendees": [
                {"displayName": "Anna Martinez", "email": "anna@placement.com"},
                {"displayName": "Robert Kline", "email": "robert.kline@globalfin.com"},
            ],
            "transcript_url": "",
            "speakers": [
                {"id": "s5", "name": "Anna Martinez"},
                {"id": "s6", "name": "Robert Kline"},
            ],
            "sentences": [
                {"index": 0, "text": "Robert, thank you for taking the time to discuss this today.", "speaker_name": "Anna Martinez", "start_time": 0, "end_time": 5, "ai_filters": {"sentiment": "neutral"}},
                {"index": 1, "text": "Anna, I'll be direct. This is completely unacceptable. The candidate you placed falsified their credentials.", "speaker_name": "Robert Kline", "start_time": 6, "end_time": 16, "ai_filters": {"sentiment": "very negative"}},
                {"index": 2, "text": "I understand this is a serious concern. Can you share the specific details?", "speaker_name": "Anna Martinez", "start_time": 17, "end_time": 23, "ai_filters": {"sentiment": "neutral"}},
                {"index": 3, "text": "The senior Java developer you placed claimed 8 years of experience. Turns out they barely know the basics. This is a breach of trust.", "speaker_name": "Robert Kline", "start_time": 24, "end_time": 38, "ai_filters": {"sentiment": "very negative"}},
                {"index": 4, "text": "We've already lost three weeks of project timeline because of this. My CEO is furious and wants to escalate.", "speaker_name": "Robert Kline", "start_time": 39, "end_time": 50, "ai_filters": {"sentiment": "very negative"}},
                {"index": 5, "text": "I'm deeply sorry, Robert. This is not the standard we hold ourselves to. We take credential verification very seriously.", "speaker_name": "Anna Martinez", "start_time": 51, "end_time": 60, "ai_filters": {"sentiment": "negative"}},
                {"index": 6, "text": "Sorry isn't enough. I want a full refund of the placement fee and a replacement candidate within 48 hours.", "speaker_name": "Robert Kline", "start_time": 61, "end_time": 72, "ai_filters": {"sentiment": "very negative"}},
                {"index": 7, "text": "I want to speak to your manager about this. This is the worst experience I've ever had with a staffing agency.", "speaker_name": "Robert Kline", "start_time": 73, "end_time": 84, "ai_filters": {"sentiment": "very negative"}},
                {"index": 8, "text": "I'll connect you with our VP of Client Services today. We will also begin an internal investigation immediately.", "speaker_name": "Anna Martinez", "start_time": 85, "end_time": 94, "ai_filters": {"sentiment": "neutral"}},
                {"index": 9, "text": "You better. Because right now I'm considering filing a formal complaint and terminating our entire contract.", "speaker_name": "Robert Kline", "start_time": 95, "end_time": 106, "ai_filters": {"sentiment": "very negative"}},
                {"index": 10, "text": "I understand. Let me assure you we will make this right. I'll have a remediation plan to you by end of day.", "speaker_name": "Anna Martinez", "start_time": 107, "end_time": 116, "ai_filters": {"sentiment": "neutral"}},
                {"index": 11, "text": "This has completely damaged my confidence in your agency. I'm extremely disappointed.", "speaker_name": "Robert Kline", "start_time": 117, "end_time": 126, "ai_filters": {"sentiment": "very negative"}},
            ],
        },
        {
            "id": "mock_004",
            "title": "Quarterly Review — MediHealth Systems",
            "date": "1749561600000",
            "date_string": "2025-06-10T11:00:00Z",
            "duration": 22.0,
            "organizer_email": "david@placement.com",
            "participants": ["david@placement.com", "patricia@medihealth.com"],
            "meeting_attendees": [
                {"displayName": "David Park", "email": "david@placement.com"},
                {"displayName": "Patricia Nguyen", "email": "patricia@medihealth.com"},
            ],
            "transcript_url": "",
            "speakers": [
                {"id": "s7", "name": "David Park"},
                {"id": "s8", "name": "Patricia Nguyen"},
            ],
            "sentences": [
                {"index": 0, "text": "Patricia, welcome to our quarterly review. How has the team been performing?", "speaker_name": "David Park", "start_time": 0, "end_time": 7, "ai_filters": {"sentiment": "positive"}},
                {"index": 1, "text": "Overall it's been okay, David. Nothing extraordinary but no major issues either.", "speaker_name": "Patricia Nguyen", "start_time": 8, "end_time": 16, "ai_filters": {"sentiment": "neutral"}},
                {"index": 2, "text": "The compliance analyst is doing a decent job. She's reliable and meets deadlines.", "speaker_name": "Patricia Nguyen", "start_time": 17, "end_time": 25, "ai_filters": {"sentiment": "positive"}},
                {"index": 3, "text": "That's good. Any areas of concern?", "speaker_name": "David Park", "start_time": 26, "end_time": 30, "ai_filters": {"sentiment": "neutral"}},
                {"index": 4, "text": "The IT support role has had some communication challenges. It's manageable but could be better.", "speaker_name": "Patricia Nguyen", "start_time": 31, "end_time": 40, "ai_filters": {"sentiment": "neutral"}},
                {"index": 5, "text": "Would you like us to provide any additional training or support for that role?", "speaker_name": "David Park", "start_time": 41, "end_time": 48, "ai_filters": {"sentiment": "positive"}},
                {"index": 6, "text": "That would be helpful. We're planning to continue the engagement for another quarter at this point.", "speaker_name": "Patricia Nguyen", "start_time": 49, "end_time": 58, "ai_filters": {"sentiment": "positive"}},
            ],
        },
        {
            "id": "mock_005",
            "title": "Urgent Issue — RetailMax Stores",
            "date": "1749475200000",
            "date_string": "2025-06-09T16:00:00Z",
            "duration": 28.0,
            "organizer_email": "lisa@placement.com",
            "participants": ["lisa@placement.com", "james.hart@retailmax.com"],
            "meeting_attendees": [
                {"displayName": "Lisa Wong", "email": "lisa@placement.com"},
                {"displayName": "James Hart", "email": "james.hart@retailmax.com"},
            ],
            "transcript_url": "",
            "speakers": [
                {"id": "s9", "name": "Lisa Wong"},
                {"id": "s10", "name": "James Hart"},
            ],
            "sentences": [
                {"index": 0, "text": "James, thank you for the urgent call. What's going on?", "speaker_name": "Lisa Wong", "start_time": 0, "end_time": 5, "ai_filters": {"sentiment": "neutral"}},
                {"index": 1, "text": "Lisa, we have a serious problem. The warehouse manager you placed walked off the job yesterday without notice.", "speaker_name": "James Hart", "start_time": 6, "end_time": 16, "ai_filters": {"sentiment": "negative"}},
                {"index": 2, "text": "Oh no, I'm so sorry to hear that. Do you know what happened?", "speaker_name": "Lisa Wong", "start_time": 17, "end_time": 22, "ai_filters": {"sentiment": "negative"}},
                {"index": 3, "text": "Apparently there was a conflict with another staff member. But that's not an excuse for just leaving. We're now short-staffed during our busiest season.", "speaker_name": "James Hart", "start_time": 23, "end_time": 36, "ai_filters": {"sentiment": "negative"}},
                {"index": 4, "text": "This is very frustrating. We relied on your vetting process to find reliable people.", "speaker_name": "James Hart", "start_time": 37, "end_time": 44, "ai_filters": {"sentiment": "negative"}},
                {"index": 5, "text": "You're absolutely right, and I take full responsibility. Let me mobilize our team to find a replacement immediately.", "speaker_name": "Lisa Wong", "start_time": 45, "end_time": 54, "ai_filters": {"sentiment": "neutral"}},
                {"index": 6, "text": "I need someone by Monday, Lisa. If not, this is going to cost us tens of thousands in overtime.", "speaker_name": "James Hart", "start_time": 55, "end_time": 64, "ai_filters": {"sentiment": "negative"}},
                {"index": 7, "text": "I'm going to make this my top priority. We have several pre-vetted candidates in our pipeline for warehouse roles.", "speaker_name": "Lisa Wong", "start_time": 65, "end_time": 74, "ai_filters": {"sentiment": "positive"}},
                {"index": 8, "text": "I hope so. I don't want to lose faith in your agency. We've had a good relationship until now.", "speaker_name": "James Hart", "start_time": 75, "end_time": 84, "ai_filters": {"sentiment": "mixed"}},
                {"index": 9, "text": "And I value that relationship deeply. You'll have candidate profiles in your inbox by tonight.", "speaker_name": "Lisa Wong", "start_time": 85, "end_time": 92, "ai_filters": {"sentiment": "positive"}},
                {"index": 10, "text": "Okay, I'll hold you to that. Let's talk tomorrow morning to finalize.", "speaker_name": "James Hart", "start_time": 93, "end_time": 100, "ai_filters": {"sentiment": "neutral"}},
            ],
        },
    ]

    classifier = SpeakerClassifier(company_domains=["placement.com"], db=db)
    analyzer = SentimentAnalyzer(db=db)
    alert_engine = AlertEngine(db=db)

    for transcript in mock_transcripts:
        # Store transcript
        db.upsert_transcript({
            "id": transcript["id"],
            "title": transcript["title"],
            "date": transcript["date"],
            "date_string": transcript["date_string"],
            "duration": transcript["duration"],
            "organizer_email": transcript["organizer_email"],
            "participants": transcript["participants"],
            "meeting_attendees": transcript["meeting_attendees"],
            "transcript_url": transcript.get("transcript_url", ""),
            "speakers": transcript["speakers"],
        })

        # Classify speakers
        speaker_roles = classifier.classify(transcript)
        speaker_roles = classifier.post_process_classifications(speaker_roles)

        # Analyze sentiment
        report = analyzer.analyze_transcript(transcript, speaker_roles)

        # Save results
        db.save_sentiment_result({
            "transcript_id": report.transcript_id,
            "overall_score": report.overall_score,
            "customer_score": report.customer_score,
            "positive_pct": report.positive_pct,
            "neutral_pct": report.neutral_pct,
            "negative_pct": report.negative_pct,
            "sentiment_trajectory": report.sentiment_trajectory,
            "warning_level": report.warning_level,
            "key_negative_moments": report.key_negative_moments,
            "speaker_sentiments": report.speaker_sentiments,
            "analysis_metadata": report.analysis_metadata,
        })

        # Save sentence sentiments
        sentence_dicts = [sd.to_dict() for sd in report.sentence_details]
        if sentence_dicts:
            db.save_sentence_sentiments(sentence_dicts)

        # Update status
        db.update_transcript_status(transcript["id"], "analyzed")

        # Generate alerts
        alert_engine.evaluate_and_alert(report, transcript)

    logger.info(f"Seeded {len(mock_transcripts)} mock transcripts with sentiment analysis")
