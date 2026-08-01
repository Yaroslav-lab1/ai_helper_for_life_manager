\set ON_ERROR_STOP on

SELECT format(
  'ALTER ROLE %I WITH PASSWORD %L',
  :'role_name',
  :'new_password'
)
\gexec
