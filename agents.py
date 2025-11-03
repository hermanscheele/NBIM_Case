from utils import spinner, write_json_file, write_to_outbox
from safeguards import apply_safeguards
import json, uuid, os
from datetime import datetime, timezone
from prompts import BREAK_DIAGNOSIS_PROMPT, POLICY_AGENT_PROMPT, AUTO_RESOLUTION_PROMPT, REMEDIATION_DRAFT_PROMPT
from sub_agents import contextualize_policy_text




# ---------------------- MARKET VALIDATION AGENT ----------------------- #

def market_validation_agent(breaks, model, client):
    print("")

    results = []
    
    for i, brk in enumerate(breaks, 1):
        
        # Get country from ISIN
        isin = brk.get('isin', '')
        country_map = {
            'KR': 'South Korea', 'CH': 'Switzerland', 'US': 'United States',
            'GB': 'United Kingdom', 'JP': 'Japan', 'DE': 'Germany', 'FR': 'France'
        }
        country = country_map.get(isin[:2], isin[:2]) if len(isin) >= 2 else 'Unknown'
        
        # Simple query
        query = f"""
            Search public sources for market standards regarding:

            ISIN: {isin}
            Country: {country}
            Custodian: {brk.get('custodian')}
            Break type: {brk.get('type')}
            Ex-date: {brk.get('ex_date')}
            Pay-date: {brk.get('pay_date')}

            Find official dividend details, tax rates, and payment dates.

            Determine: Is this break due to "internal" (NBIM error) or "external" (standard market practice)?

            IMPORTANT: In the "sources" field, include the actual HTTPS URLs of the websites you found, not search references.

            Return ONLY this JSON (no markdown, no explanations):
            {{
                "break_id": {i},
                "issuer_country": "{country}",
                "custodian": "{brk.get('custodian')}",
                "public_info_summary": "<short summary of market standard>",
                "likely_source": "internal|external|uncertain",
                "reason": "<one sentence why>",
                "sources": ["https://example.com/page1", "https://example.com/page2"]
            }}
            """
        
        stop = spinner(f"Market research for break: {i}/{len(breaks)}...")
        response = client.responses.create(
            model=model,
            tools=[{"type": "web_search"}],
            input=query
        )
        stop()
        
        # Parse response
        try:
            parsed = json.loads(response.output_text)
        except:
            parsed = {"break_id": i, "error": "parse_error", "raw": response.output_text}
        
        results.append(parsed)
    
    write_json_file(results, "market_agent")
    return results





# ---------------------- BREAK DIAGNOSIS AGENT ----------------------- #

def break_diagnosis_agent(breaks, market_validation, model, client):
    print("")
    
    user_msg = f"""
        You are diagnosing dividend reconciliation breaks.

        BREAKS DETECTED:
        {json.dumps(breaks, indent=2)}

        MARKET VALIDATION RESULTS (verified external facts):
        {json.dumps(market_validation, indent=2)}

        {BREAK_DIAGNOSIS_PROMPT}
        """
    
    stop = spinner(f"Diagnosing {len(breaks)} breaks with market facts...")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a financial reconciliation expert."},
            {"role": "user", "content": user_msg}
        ],
        response_format={"type": "json_object"}
    )
    stop()

    result = json.loads(response.choices[0].message.content)
    
    diagnosed_count = len(result.get('diagnosis', []))
    print(f"✓ Diagnosed {diagnosed_count}/{len(breaks)} breaks")
    
    if diagnosed_count != len(breaks):
        print(f"⚠️  Warning: Missing {len(breaks) - diagnosed_count} diagnoses")
    
    write_json_file(result, "break")
    return result






# ---------------------- POLICY & COMPLIANCE AGENT ----------------------- #

def policy_agent(breaks, diagnosis, policy_text, model, client):
    print("")

    policy_context = contextualize_policy_text(policy_text, model)

    user_msg = f"""
        Check if these breaks and their diagnoses violate any policies:

        BREAKS: {json.dumps(breaks, indent=2)}
        DIAGNOSIS: {json.dumps(diagnosis, indent=2)}
        POLICY: {policy_text}
        POLICY CONTEXTUALIZED: {policy_context}

        {POLICY_AGENT_PROMPT}
        """
    
    stop = spinner("Checking policy compliance...")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a policy compliance expert."},
            {"role": "user", "content": user_msg}
        ],
        response_format={"type": "json_object"}
    )
    stop()

    result = json.loads(response.choices[0].message.content)
    print("✓ Policy check complete")
    
    write_json_file(result, "policy")

    return result





# ---------------------- SAFEGUARDED AUTO-RESOLTUONS AGENT ----------------------- #

def auto_resolution_agent(breaks, diagnosis, policy_eval, model, client):
    print("")
    
    user_msg = f"""
        Analyze these breaks and determine resolution approach for each.

        BREAKS: {breaks}
        DIAGNOSIS: {diagnosis}
        POLICY EVALUATION: {policy_eval}

        {AUTO_RESOLUTION_PROMPT}
        """
    
    stop = spinner(f"Determining resolution approach for {len(breaks)} breaks...")    
    response = client.chat.completions.create(
        model=model,
        temperature=0.1,
        messages=[
            {"role": "system", "content": "You are an auto-resolution decision expert. Output only valid JSON."},
            {"role": "user", "content": user_msg}
        ]
    )
    stop()
    
    result = json.loads(response.choices[0].message.content)
    
    # Validate count
    resolutions_count = len(result.get("resolutions", []))
    if resolutions_count != len(breaks):
        print(f"Warning: Only {resolutions_count}/{len(breaks)} breaks have resolutions")
    
    # APPLY SAFEGUARDS (Deterministic)
    print("\n⚠️  Applying safety rules...")
    print(f"   LLM suggested {sum(1 for r in result.get('resolutions', []) if r.get('auto_fixable'))} auto-fixes")
    override_count = apply_safeguards(result.get("resolutions", []), breaks, diagnosis)
    print(f"   Safety blocked {override_count} fixes")
    
    # Recalculate summary after safeguards
    final_auto_count = sum(1 for r in result.get("resolutions", []) if r.get("auto_fixable"))
    result["summary"]["auto_fixable"] = final_auto_count
    result["summary"]["human_required"] = len(breaks) - final_auto_count
    result["summary"]["safeguard_overrides"] = override_count
    
    # Add metadata
    result["metadata"] = {
        "total_breaks": len(breaks),
        "resolutions_generated": resolutions_count,
        "model_used": model,
        "safeguards_applied": override_count
    }
    
    # Write to file
    write_json_file(result, "auto_resolution")
    
    print(f"\n✓ Resolution analysis complete:")
    print(f"  - Auto-fixable: {result['summary'].get('auto_fixable', 0)}")
    print(f"  - Human required: {result['summary'].get('human_required', 0)}")
    print(f"  - Safety overrides: {override_count}")
    
    return result






# ---------------------- REMEDIATION AGENT ----------------------- #

def remediation_agent(breaks, diagnosis, market_facts, model, client):
    print("")

    # Step 1 — ask to draft
    print("")
    confirm = input(f"Draft remediation requests with {model}? [y/N]: ").strip().lower()
    if confirm not in ("y","yes"):
        print("Aborted before drafting.")
        return {"status": "aborted_before_draft"}

    user_msg = f"""
        BREAKS: {breaks}
        MARKET_FACTS: {market_facts}
        BREAK_DIAGNOSIS: {diagnosis}


        {REMEDIATION_DRAFT_PROMPT}
        """


    stop = spinner(f"Drafting remediation notes for {len(breaks)} breaks...")
    res = client.chat.completions.create(
        model=model,
        temperature=0.2,
        response_format={"type":"json_object"},
        messages=[
            {"role":"system","content":"You are a precise financial ops assistant. Output only JSON."},
            {"role":"user","content":user_msg}
        ]
    )
    stop()


    data = json.loads(res.choices[0].message.content)
    
    
    # Add metadata + draft IDs
    for d in data.get("remediations",[]):
        d["draft_id"] = str(uuid.uuid4())[:8]
        d["created_at"] = datetime.now(timezone.utc).isoformat()


    write_json_file(data, "remediation_drafts")
    print("✓ Drafts saved in agent_output/remediation_drafts.json")




    # Step 2 — ask to send
    print("")
    confirm2 = input("Send drafts to custodians (outbox)? [y/N]: ").strip().lower()
    if confirm2 not in ("y","yes"):
        print("Drafting completed. Sending not authorized.")
        return {"status": "drafts_only"}

    stop = spinner("Writing custodian outbox files...")
    count = 0

    [os.remove(f"custody_outbox/{f}") for f in os.listdir("custody_outbox")]
    for d in data.get("remediations", []):
        cust = (d.get("custodian") or "CUST_").replace("/", "_")
        write_to_outbox(d, cust)
        count += 1
    stop()

    print(f"✓ Outbox updated for {count} message(s).")
    return {"status": "queued_for_send", "count": count}