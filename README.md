# Full stack developer Project 4: Conference Central
Conference Central is a cloud-based API server built on Google Cloud Platform. 
This project is part of [Udacity’s Full Stack Web Developer Nanodegree](https://www.udacity.com/course/nd004).

The API supports the following functionality:

- User authentication 
- Create, read, update conferences and sessions
- Register/deregister for conferences
- Add/remove sessions to user's wish list
- Task Queues and Cron Jobs such as:
    - Email confirmation upon conference creation
    - Update conference announcements in Memcache. (updates every hour)
    - Update most recent featured speaker in Memcache. (checked after session creation)  

Website is available at [cloud9-conf][2]. Though it missed session related endpoint.
Though all functionality can be available using [API Explorer][1]

## Task 1 
## NDB Entities (Models)
- Profile:
    - is an "ancestor" of Conference, for the conference creator
    - "has" Conferences, when registering to a conference
    - "has" Sessions, when adding session to user's wish list
- Conference:
    - is a sibling of Profile
    - is an "ancestor" of sessions
- Session:
    - is a sibling of Conference
    - contains a Speaker (structured property)
- Speaker:
    - is a structured property. 

Conference was considered as an ancestor of Session so it use the conference key to obtain all sessions registered in the conference.

Note:
- Date, YYY-MM-DD, or a time, HH:MM, were updated to to use DateProperty and TimeProperty.

## Task 2:
Suggested endpoints are implemented and can be accessed using [API expolrer][1].

## Task 3: Queries

Let’s say that you don't like workshops and you don't like sessions after 7 pm. 
How would you handle a query for all non-workshop sessions before 7 pm?
- `Session.query(Session.typeOfSession != 'workshop', Session.startTime < time(19) )`

What is the problem for implementing this query?
- NDB Datastore API support inequalities only for single property whereas in the problem we were asked to perform inequalities for multiple properties.

What ways to solve it did you think of?
- One solution is to let datastore handle the first inequality and any additional inequalities should be implemented in python.

The endpoint 'getTypewithTime' use the above approach.

## Additional Queries

`gethourSessions()` - Return session which are of an hour or less.

`querySessions()` - Given a `SessionQueryForms`, returns a set of filtered sessions.

[1]: https://cloud9-conf.appspot.com/_ah/api/explorer
[2]: https://cloud9-conf.appspot.com/#/
