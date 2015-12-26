#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'


from datetime import datetime,time

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.ext import ndb

from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import TeeShirtSize
from models import SessionType,Speaker,Session,SessionForm,SessionForms
from models import SessionQueryForm,SessionQueryForms

from utils import getUserId
from settings import WEB_CLIENT_ID

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID

from models import Conference
from models import ConferenceForm


DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

CONF_FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

SESSION_FIELDS =    {
            'NAME': 'name',
            'DURATION': 'duration',
            'TYPE_OF_SESSION': 'typeOfSession',
            'Date': 'date',
            'START_TIME':'startTime',
            'SPEAKER':'speaker',
            }
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
from models import BooleanMessage
from models import ConflictException

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_SPEAKER_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker=messages.StringField(1, required=True),
)

SESSION_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1, required=True)
)

SESSION_TYPE_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1, required=True),
    sessionType=messages.StringField(2, required=True)
)

SESSION_WISHLIST_POST_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeSessionKey=messages.StringField(1, required=True)
)

SESSION_REQUIRED_FIELDS = ('name', 'speaker', 'duration', 'typeOfSession', 'date', 'startTime')

MEMCACHE_ANNOUNCEMENTS_KEY="LATEST_ANNOUNCEMENT"
MEMCACHE_FEATURED_SPEAKER_KEY="FEATURED_SPEAKER"

from google.appengine.api import memcache

from models import StringMessage

from google.appengine.api import taskqueue

@endpoints.api( name='conference',
                version='v1',
                allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID],
                scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Profile objects - - - - - - - - - - - - - - - - - - -
    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # retrieve profile from datastore
        user_id=getUserId(user)
        p_key = ndb.Key(Profile,user_id)
        profile = p_key.get()
        # create profile if not exist
        if not profile:
            profile = Profile(
                key = p_key, # TODO 1 step 4. replace with the key from step 3
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        #if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        #else:
                        #    setattr(prof, field, val)
            prof.put()

        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf


    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        # both for data model & outbound Message
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
            setattr(request, "seatsAvailable", data["maxAttendees"])

        # make Profile Key from user ID
        p_key = ndb.Key(Profile, user_id)
        # allocate new Conference ID with Profile key as parent
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        # make Conference key from ID
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )
        return request


    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)


    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)
        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName
        # return individual ConferenceForm object per Conference
        return ConferenceForms(
        items=[self._copyConferenceToForm(conf,names[conf.organizerUserId]) \
        for conf in conferences]
        )


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
        path='getConferencesCreated',
        http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # make profile key
        p_key = ndb.Key(Profile, getUserId(user))
        # create ancestor query for this user
        conferences = Conference.query(ancestor=p_key)
        # get the user profile and display name
        prof = p_key.get()
        displayName = getattr(prof, 'displayName')
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, displayName) for conf in conferences]
        )


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
        path='filterPlayground',
        http_method='GET', name='filterPlayground')
    def filterPlayground(self, request):
        q = Conference.query()
        # simple filter usage:
        # q = q.filter(Conference.city == "Paris")

        # advanced filter building and usage
        field = "city"
        operator = "="
        value = "London"
        f = ndb.query.FilterNode(field, operator, value)
        q = q.filter(f)
        q=q.order(Conference.maxAttendees)

        # filter for month of june
        q=q.filter(Conference.maxAttendees > 6)

        # TODO
        # add 2 filters:
        # 1: city equals to London
        # 2: topic equals "Medical Innovations"

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )


    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters,type='Conference'):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                if type == 'Conference':
                    filtr["field"] = CONF_FIELDS[filtr["field"]]
                elif type == 'Session':
                    filtr["field"] = SESSION_FIELDS[filtr["field"]]

                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


    #@ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""

        prof = self._getProfileFromUser()
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # retrieve organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf,
        names[conf.organizerUserId])\
         for conf in conferences]
        )


# - - - Announcements - - - - - - - - - - - - - - - - - - - -
    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = '%s %s' % (
                'Last chance to attend! The following conferences '
                'are nearly sold out:',
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement


    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        announcement = memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY)
        if not announcement:
            announcement = ""
        return StringMessage(data=announcement)

# - - - Conference Session - - - - - - - - - - - - - - - - - - - -
    @endpoints.method(CONF_GET_REQUEST, SessionForms,
                      path='conference/{websafeConferenceKey}/sessions',
                      http_method='GET',
                      name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Given a conference, return all sessions"""
        # get Conference object from request
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException('No conference found with key: %s' % request.websafeConferenceKey)

        # Return  set of SessionForm belong to Conference
        return SessionForms(items=[self._copySessionToForm(session) for session in conf.sessions])


    @endpoints.method(SESSION_TYPE_GET_REQUEST,
                      SessionForms,
                      path='conference/{websafeConferenceKey}/sessions/type/{sessionType}',
                      http_method='GET',
                      name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Given a conference, return all sessions of a specified type (eg lecture, keynote, workshop)"""
        # get Conference object from request
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException('No conference found with key: %s' % request.websafeConferenceKey)

        # filter sessions by session type
        sessions = conf.sessions.filter(Session.typeOfSession == str(request.sessionType))

        # Return a set of SessionForm objects per session
        return SessionForms(items=[self._copySessionToForm(session) for session in sessions])


    @endpoints.method(SESSION_SPEAKER_GET_REQUEST,
                      SessionForms,
                      path='sessions/speaker/{speaker}',
                      http_method='GET',
                      name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """Given a speaker, return all sessions given by this particular speaker, across all conferences"""
        #filter session by speaker
        sessions = Session.query(Session.speaker == Speaker(name=request.speaker))

        # Return a set of SessionForm objects per session
        return SessionForms(items=[self._copySessionToForm(session) for session in sessions])


    def _createSessionObject(self, sessionForm):
        """Create Session object, return SessionForm."""
        # ensure user is authenticated
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get the conference
        conf = ndb.Key(urlsafe=sessionForm.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException('No conference found with key: %s' % sessionForm.conferenceKey)

        # ensure ownership
        if getUserId(user) != conf.organizerUserId:
            raise endpoints.ForbiddenException('Only organizer of conference : %s can add sessions.' % conf.name)

        # copy SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(sessionForm, field.name) for field in sessionForm.all_fields()}
        # convert typeOfsession to string
        if data['typeOfSession']:
            data['typeOfSession']=str(data['typeOfSession'])
        else:
            data['typeOfSession']=str(SessionType.NOT_SPECIFIED)
        del data['websafeKey']
        del data['websafeConferenceKey']

        # check required fields
        for key in SESSION_REQUIRED_FIELDS:
            if not data[key]:
                raise endpoints.BadRequestException("'%s' field is required to create a session." % key)

        # convert date string to a datetime object.
        try:
            data['date'] = datetime.strptime(data['date'][:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            raise endpoints.BadRequestException("Invalid date format. Please use 'YYYY-MM-DD'")

        # convert date string to a time object. HH:MM
        try:
            data['startTime'] = datetime.strptime(data['startTime'][:5], "%H:%M").time()
        except (TypeError, ValueError):
            raise endpoints.BadRequestException("Invalid date format. Please use 'HH:MM'")

        if data['duration'] <= 0:
            raise endpoints.BadRequestException("Duration must be greater than zero")
        #session must be within conference start and end date only when dates
        #defined  at the time of conference creation
        if conf.startDate and conf.endDate :
            if data['date'] < conf.startDate or data['date'] > conf.endDate:
                raise endpoints.BadRequestException("Session must be within range of conference start and end date")

        data['speaker'] = Speaker(name=data['speaker'])
        # Datastore to allocate an ID.
        s_id = Session.allocate_ids(size=1, parent=conf.key)[0]
        # Datastore returns an integer ID that we can use to create a session key
        data['key'] = ndb.Key(Session, s_id, parent=conf.key)
        # Add session to datastore
        session = Session(**data)
        session.put()

        # Add a task to check and update new featured speaker
        taskqueue.add(
            params={'websafeConferenceKey': conf.key.urlsafe(), 'speaker': session.speaker.name},
            url='/tasks/set_featured_speaker'
        )

        return self._copySessionToForm(session)

    @endpoints.method(SESSION_POST_REQUEST,
                      SessionForm,
                      path='conference/sessions/{websafeConferenceKey}',
                      http_method='POST',
                      name='createSession')
    def createSession(self, request):
        """Creates a session, open to the organizer of the conference"""
        return self._createSessionObject(request)


    def _copySessionToForm(self,session):
        """Copy fields from Session to SessionForm."""
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(session, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('date'):
                    setattr(sf, field.name, getattr(session, field.name).strftime('%Y-%m-%d'))
                elif field.name.endswith('startTime'):
                    setattr(sf, field.name, getattr(session, field.name).strftime('%H:%M'))
                elif field.name.endswith('speaker'):
                    setattr(sf, field.name, session.speaker.name)
                elif field.name.endswith('typeOfSession'):
                    setattr(sf, field.name, getattr(SessionType, getattr(session, field.name)))
                else:
                    setattr(sf, field.name, getattr(session, field.name))
            elif field.name == "websafeKey":
                setattr(sf, field.name, session.key.urlsafe())

        sf.check_initialized()
        return sf


    @endpoints.method(SESSION_WISHLIST_POST_REQUEST,
                      BooleanMessage,
                      path='profile/wishlist/{websafeSessionKey}',
                      http_method='POST',
                      name='addSessionToWishlist')
    @ndb.transactional(xg=True)
    def addSessionToWishlist(self, request):
        """adds the session to the user's list of sessions they are interested in attending"""
        # get user Profile
        prof = self._getProfileFromUser()
        # get session and check if it exists
        key = ndb.Key(urlsafe=request.websafeSessionKey)
        session = key.get()

        if not session:
            raise endpoints.BadRequestException("Session with key %s doesn't exist" % request.sessionKey)
        # ensure is not already in user's wishlist
        if key in prof.wishList:
            raise ConflictException("This session is already in user's wishlist")
        # add session to user's list
        prof.wishList.append(key)
        prof.put()
        return BooleanMessage(data=True)


    @endpoints.method(message_types.VoidMessage,
                      SessionForms,
                      path='profile/wishlist/all',
                      http_method='GET',
                      name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """query for all the sessions in a conference that the user is interested in"""
        # get user Profile
        prof = self._getProfileFromUser()
        # get all sessions in user's wishlist
        sessions = ndb.get_multi(prof.wishList)
        # return a set of `SessionForm` objects
        return SessionForms(items=[self._copySessionToForm(session) for session in sessions])


    @endpoints.method(SESSION_WISHLIST_POST_REQUEST,
                      BooleanMessage,
                      path='profile/wishlist/{websafeSessionKey}',
                      http_method='DELETE',
                      name='deleteSessionInWishlist')
    @ndb.transactional()
    def deleteSessionInWishlist(self, request):
        """removes the session from the user’s list of sessions they are interested in attending"""
        # get user Profile
        prof = self._getProfileFromUser()
        key = ndb.Key(urlsafe=request.websafeSessionKey)
        # get session the session key and check if it exists in user's wish list
        if key not in prof.wishList:
            raise endpoints.BadRequestException("Failed to find session in user's wishlist")
        # remove session from user's wishlist
        prof.wishList.remove(key)
        prof.put()
        return BooleanMessage(data=True)

    #additional query endpoint

    @endpoints.method(message_types.VoidMessage,
                     SessionForms,
                     path='conference/sessions/hour',
                     http_method='GET',
                     name='gethourSessions')
    def gethourSessions(self,request):
        """ Return all sessions that are of an hour or less """
        sessions = Session.query(Session.duration <= 60)
        #here duration is specified in minutes
        return SessionForms(items=[self._copySessionToForm(session) for session in sessions])


    def _getSessionQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Session.query()
        inequality_filter, filters = self._formatFilters(request.filters,type='Session')

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Session.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Session.name)

        for filtr in filters:
            if filtr["field"] in ["duration"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    @endpoints.method(SessionQueryForms,
                      SessionForms,
                      path='querySessions',
                      http_method='POST',
                      name='querySessions')
    def querySessions(self, request):
        """Query for sessions."""
        # use `SESSION_FIELDS` to construct query.
        sessions = self._getSessionQuery(request)
        return SessionForms(items=[self._copySessionToForm(session) for session in sessions])

    #special query problem
    @endpoints.method(SESSION_POST_REQUEST,
                      SessionForms,
                      path='conference/{websafeConferenceKey}/sessions/typewithtime',
                      http_method='GET',
                      name='getTypewithTime')
    def getTypewithTime(self,request):
        """Special query that handle couple of inequalities"""
        wck=request.websafeConferenceKey
        # get conference object
        confKey=ndb.Key(urlsafe=wck)
        if not confKey.get():
            raise endpoints.NotFoundException('No conference found with key : %s' % wck)

        query=Session.query(ancestor=confKey)
        query=query.filter(Session.typeOfSession != str(SessionType.workshop))
        query=query.order(Session.typeOfSession)
        query=query.order(Session.date)
        query=query.order(Session.startTime)

        results=[session for session in query if session.startTime < time(19)]

        return SessionForms(items=[self._copySessionToForm(session) for session in results])

    @endpoints.method(message_types.VoidMessage,
                      StringMessage,
                      path='conference/featured_speakers/get',
                      http_method='GET',
                      name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Returns featured speaker along with their sessions from memcache"""
        return StringMessage(data=memcache.get(MEMCACHE_FEATURED_SPEAKER_KEY) or "")


# registers API
api = endpoints.api_server([ConferenceApi])
