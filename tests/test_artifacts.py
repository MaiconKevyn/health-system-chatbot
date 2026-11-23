from health_system_chatbot.artifacts import load_stage1_context


def test_load_stage1_context_excludes_evaluation_labels_and_loads_join_policy():
    ctx = load_stage1_context()

    assert ctx.ground_truth == []
    assert "internacao" in ctx.tables
    assert "COD_IDADE" in ctx.tables["internacao"].columns
    assert any(policy.confidence == "rejected" for policy in ctx.join_policies)
    assert any(
        policy.accepted_usage_policy == "left_join_or_explicit_mapped_scope_required"
        for policy in ctx.join_policies
    )


def test_load_stage1_context_can_sync_with_runtime_duckdb_catalog(tmp_path):
    import duckdb

    db_path = tmp_path / "runtime.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            "CREATE TABLE _staging_internacoes (CAR_INT TINYINT, PROC_REA VARCHAR)"
        )
        con.execute("INSERT INTO _staging_internacoes VALUES (1, 'P001')")
        con.execute(
            "CREATE TABLE internacoes (N_AIH VARCHAR, CAR_INT TINYINT, PROC_REA VARCHAR)"
        )
        con.execute("INSERT INTO internacoes VALUES ('AIH1', 1, 'P001')")
        con.execute("CREATE TABLE car_int (CAR_INT TINYINT, DESCRICAO VARCHAR)")
        con.execute("INSERT INTO car_int VALUES (1, 'Urgencia')")
    finally:
        con.close()

    ctx = load_stage1_context(db_path=db_path)

    assert "_staging_internacoes" in ctx.tables
    assert "CAR_INT" in ctx.tables["_staging_internacoes"].columns
    assert ctx.tables["_staging_internacoes"].column_types["PROC_REA"] == "VARCHAR"
    assert "internacao_procedimento" not in ctx.tables
    assert all(
        policy.left.split(".")[0] in ctx.tables and policy.right.split(".")[0] in ctx.tables
        for policy in ctx.join_policies
    )
