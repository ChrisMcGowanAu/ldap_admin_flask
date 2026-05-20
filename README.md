# LDAP Admin Flask Tool – pretty UI + username collision + editable Check User + Bulk imports via csv + Full report of users in spreadsheet.
Background:
This tool was first built for Lorien Novalis school (NSW Australia) to help manage our LDAP database. There was a need to being able to do bulk additions as the school has a need for this at the beginning of each school term. It has a facility to generate kid friendly passwords, that are reasonably strong yet not hard to remember, There passwords are used for wi-fi login, teams login and the Linux student machines. 
The tool can be configured to handle the common home setup of /home/USER, or the school setup Lorien uses, which is the year of graduation as the group. For example, for students graduating in 2030 the group name is Class2030 and the groupiD id 2030. Thus these year 8 students (in 2026 ) have a base home of /lorienNet/Class2030. 
Adding new users is quite easy, and adding a batch of new users can be done via a csv file. The tool will even generate passwords for the new users in the batch file, and create new home directories and email adresses.
Whilst there are some good tools around to manage LDAP, we found these hard to use and were limited to adding one user at a time, or forces to use DIY shell scripts to interface with LDAP.

Features:

- Dynamic class → cohort mapping (Class 12..7 → classYYYY home dirs)
- Login using uid (or fragment), resolved to cn=Full Name DNs under ou=people,dc=lorien
- Username generator (given name + first letter of family name)
- Password generator (TwoWordsNN?) 
- Username collision handling:
  - If requested uid exists, automatically uses uid1, uid2, ...
- Dark, prettier UI
- Check User:
  - Accepts full or partial uid (first matching entry is used)
  - Shows attributes
  - Allows editing: givenName, sn, displayName, homeDirectory, loginShell


## Local fixes included

- `TEST_MODE` default set to `False` in `config_example.py`
- Login now enforces `ADMIN_UID_ALLOWLIST` (edit in your real `config.py`)
- Username generation now uses given name + **first letter** of family name
