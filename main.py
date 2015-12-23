#!/usr/bin/env python
import webapp2
from google.appengine.api import app_identity
from google.appengine.api import mail,memcache
from conference import ConferenceApi,MEMCACHE_FEATURED_SPEAKER_KEY
from google.appengine.ext import ndb
from models import Session, Speaker

class SetAnnouncementHandler(webapp2.RequestHandler):
    def get(self):
        """Set Announcement in Memcache."""        
        ConferenceApi._cacheAnnouncement()

class SendConfirmationEmailHandler(webapp2.RequestHandler):
    def post(self):
        """Send email confirming Conference creation."""
        mail.send_mail(
            'noreply@%s.appspotmail.com' % (
                app_identity.get_application_id()),     # from
            self.request.get('email'),                  # to
            'You created a new Conference!',            # subj
            'Hi, you have created a following '         # body
            'conference:\r\n\r\n%s' % self.request.get(
                'conferenceInfo')
        )

class SetFeaturedSpeaker(webapp2.RequestHandler):
    def post(self):
        """Set featured speaker in Memcache.
        Note:
            The featured speaker is updated if there is more than
            one session by the given speaker in the provided conference (websafeConferenceKey)
            Params:
                - websafeConferenceKey
                    The conference to check for the given speaker
                - speaker
                    The possibly new featured speaker name
        """

        # get conference key 
        key = ndb.Key(urlsafe=self.request.get('websafeConferenceKey'))
        # get speaker
        speaker = Speaker(name=self.request.get('speaker'))
        # get all sessions in the given conference filtered by speaker
        featured_sessions = Session.query(ancestor=key).filter(Session.speaker == speaker).fetch()

        # If speaker is registered to more than one session, update featured speaker
        if len(featured_sessions) >= 2:
            session_names = [session.name for session in featured_sessions]
            message = speaker.name + ': ' + ', '.join(session_names)
            memcache.set(MEMCACHE_FEATURED_SPEAKER_KEY, message)

        self.response.set_status(204)

app = webapp2.WSGIApplication([
    ('/crons/set_announcement', SetAnnouncementHandler),
    ('/tasks/send_confirmation_email', SendConfirmationEmailHandler),
     ('/tasks/set_featured_speaker', SetFeaturedSpeaker)
], debug=True)