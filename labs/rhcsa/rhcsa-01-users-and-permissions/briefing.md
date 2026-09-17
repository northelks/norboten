# The Contractor Who Cannot Write

A contractor account, **kmorris**, was created last week for the **devops** team. Since then:

- kmorris cannot create or change anything in the team's shared directory, `/srv/project`.
  The rest of the team can see the directory but cannot write there either.
- When kmorris does manage to create a file somewhere, nobody else on the team can open it.
- Team members are supposed to be able to restart **nginx** with `sudo`. kmorris is told
  "not allowed".
- Someone noticed kmorris can see a few files that belong to other teams.

What the team expects, and what will be graded:

1. kmorris is a member of **devops** — and of no other team.
2. Every devops member can create and edit files in `/srv/project`.
3. Files created in `/srv/project` automatically belong to the **devops** group.
4. Files kmorris creates can be read and edited by the rest of the group, every time kmorris
   logs in.
5. devops members can run `sudo systemctl restart nginx`.

Everything must still hold after a reboot. You have root through `sudo`.
