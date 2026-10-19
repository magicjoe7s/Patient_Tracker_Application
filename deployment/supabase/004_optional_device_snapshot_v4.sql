-- Expand only the patient format allowlist; retain all deployed authorization,
-- locking, conflict, replay, and additional-format validation logic.
do $migration$
declare
    definition text := pg_get_functiondef('public.icu_sync_push(jsonb)'::regprocedure);
    needle text := $needle$v_payload->'schema_version' is distinct from '1'::jsonb$needle$;
    replacement text := $replacement$(v_payload->'schema_version' is distinct from '1'::jsonb
             and v_payload->'schema_version' is distinct from '4'::jsonb)$replacement$;
begin
    if position($supported$schema_version' is distinct from '4'::jsonb$supported$ in definition) > 0 then
        return;
    end if;
    if position(needle in definition) = 0 then
        raise exception 'Unrecognized sync validator: inspect icu_sync_push before migrating.';
    end if;
    execute replace(definition, needle, replacement);
end;
$migration$;
notify pgrst, 'reload schema';
