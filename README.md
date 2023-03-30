# Meeting Manager
 Welcome to our WXSD DEMO Repo! <!-- Keep this here --> 
 
A "Trade Floor" application that can receive PSTN calls (Webex Connect) with custom IVR, and direct the caller to a WxMeeting (by way of WxCalling).  Can receive SIP calls from devices using a static dial string and direct them to the WxMeeting as well.

This project was developed to provide a couple of methods for audio users to join a WxMeeting without using the native WxMeeting clients, and without being prompted to enter meeting access codes, or host pins.

[![Vidcast Overview](https://user-images.githubusercontent.com/19175490/228853418-d6ded84d-5ee2-4d50-85d8-11b8d9db29c8.png)](https://app.vidcast.io/share/39ebd946-ae0c-4dd9-af36-614305b5b4e3)

<!-- Keep the following here -->  
 *_Everything included is for demo and Proof of Concept purposes only. Your use of the site is solely at your own risk. This site may contain links to third party content, which we do not warrant, endorse, or assume liability for. These demos are for Cisco Webex usecases, but are not Official Cisco Webex Branded demos._

## Table of Contents <!-- Keep the following here -->  
<!-- ⛔️ MD-MAGIC-EXAMPLE:START (TOC:collapse=true&collapseText=Click to expand) -->
<details>
<summary>(click to expand)</summary>
    
  * [Overview](#overview)
  * [Setup](#setup)
  * [Demo](#demo)
  * [License](#license)  
  * [Support](#support)

</details>
<!-- ⛔️ MD-MAGIC-EXAMPLE:END -->


## Overview

The PSTN Flow:
- Caller dials a WxConnect number which triggers a WxConnect Flow.
- WxConnect Flow collects DTMF input, and sends an HTTP POST with the caller number and entered digits to our server
- WxConnect Flow patches the call to WxCalling Queue (empty)
- Our server monitors the WxCalling Queue using XSI
- When a call enters the Queue that matches the POST we received from the WxConnect Flow, we transfer the call to the WxMeeting

The SIP Flow:
- Caller dials a string in the format "meeting.PHONENUMBER.PIN@ourexpressway.exampledomain.com"
- The Cisco Expressway notifies our server (via Proxy) of the incoming call
- Our server redirects the call to the WxMeeting if the string and PIN are valid

The Server:
- Our python server.py is listening for POST requests from WxConnect and the Cisco Expressway
- Our python server.py is monitoring the WxCalling Queue
- It is also managing the scheduled meetings via the WxMeetings REST API
- Retrieving/Storing configuration information from/to MongoDB
- Managing a playwright chromium subprocess to join the meetings and mute/unmute, admit/remove participants as needed
  



### Flow Diagram

PSTN Flow  
![PSTN Flow](https://user-images.githubusercontent.com/19175490/228858319-78a67ce5-d178-4770-a7f3-e8b50cbc6815.jpg)

SIP Flow  
![SIP Flow](https://user-images.githubusercontent.com/19175490/228858322-a705f565-13fb-4efe-a99c-c166808b01ec.jpg)

The Server  
![Python Server](https://user-images.githubusercontent.com/19175490/228858325-a61a5de8-b09d-4f79-a03c-a5d1471dcda0.jpg)

## Setup

### Prerequisites & Dependencies:

- Developed on MacOS Ventura (13.2.1) & Ubuntu 22.04
- Developed on Python 3.8.1 & 3.8.3
-   Other OS and Python versions may work but have not been tested
- Mongo DB (i.e. Atlas)
- Cisco Expressway
- Webex Connect
- Webex Calling
- [Webex Integration](https://developer.webex.com/docs/integrations) with the following scopes:
```
meeting:recordings_read meeting:admin_preferences_write spark:all meeting:admin_preferences_read meeting:participants_read meeting:admin_participants_read meeting:preferences_write spark-admin:people_write meeting:transcripts_read spark:people_write spark:organizations_read meeting:schedules_write meeting:controls_read meeting:admin_config_write meeting:admin_schedule_read spark-compliance:meetings_write meeting:admin_schedule_write meeting:schedules_read spark-admin:xsi meeting:recordings_write meeting:preferences_read spark:kms meeting:controls_write meeting:admin_recordings_write spark:xsi meeting:participants_write spark-admin:licenses_read meeting:admin_config_read meeting:transcripts_write spark-admin:people_read
```

<!-- GETTING STARTED -->

### Installation Steps:
1. 
```
pip3 install playwright
playwright install
playwright install-deps

pip3 install python-dotenv
pip3 install pymongo==3.10.1
pip3 install pymongo[srv] 
pip3 install tornado==4.5.2
pip3 install requests
pip3 install requests-toolbelt
pip3 install wxcadm
pip3 install cachetools
```

2.  Clone this repo, and create a file named ```.env``` in the repo's root directory.
3.  Populate the following environment variables to the .env file:
```
MY_APP_PORT=8080
DEV_MODE=false
PYTHON_PROC_NAME=python3
MY_COOKIE_SECRET="SOME_SECRET_STRING"

WEBEX_INTEGRATION_CLIENT_ID="CLIENT_ID"
WEBEX_INTEGRATION_CLIENT_SECRET="CLIENT_SECRET"
WEBEX_INTEGRATION_REFRESH_TOKEN="REFRESH_TOKEN_FOR_ADMIN_USER_IN_YOUR_ORG_USING_THIS_INTEGRATION"

MY_MONGO_URI="mongodb+srv://yourusername:yourpassword@yourcluster.abcde.mongodb.net/YOURDB?authSource=admin&retryWrites=true&w=majority"
MY_MONGO_DB="YOURDB"
```
4. Run
```python3 server.py```
    
    
## Live Demo

<!-- Update your vidcast link -->
Check out our Vidcast recording, [here](https://app.vidcast.io/share/39ebd946-ae0c-4dd9-af36-614305b5b4e3)!

<!-- Keep the following statement -->
*For more demos & PoCs like this, check out our [Webex Labs site](https://collabtoolbox.cisco.com/webex-labs).

## License

Distributed under the MIT License. See LICENSE for more information.


## Support

Please contact the WXSD team at [wxsd@external.cisco.com](mailto:wxsd@external.cisco.com?subject=RepoName) for questions. Or for Cisco internal, reach out to us on Webex App via our bot globalexpert@webex.bot & choose "Engagement Type: API/SDK Proof of Concept Integration Development". 
