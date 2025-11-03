from break_checks import detect_breaks
from openai import OpenAI
from agents import market_validation_agent, break_diagnosis_agent, policy_agent, auto_resolution_agent, remediation_agent
from dividend_policy import POLICY_TEXT
import time





class Agent:

    def __init__(self, market_model, break_model, policy_model, resolution_model, remediation_model, nbim_file, custody_file, policy):
        

        self.client = OpenAI()

        self.market_model = market_model
        self.break_model = break_model
        self.policy_model = policy_model
        self.resolution_model = resolution_model
        self.resolution_model = remediation_model

        self.policy = policy

        self.nbim_file = nbim_file
        self.custody_file = custody_file


    def detect_breaks(self):
        return detect_breaks(self.nbim_file, self.custody_file)["breaks"]
    

    def market_validation(self, breaks):
        return market_validation_agent(breaks, self.market_model, self.client)


    def diagnose_breaks(self, breaks, market_validation):
        return break_diagnosis_agent(breaks, market_validation, self.break_model, self.client)


    def policy_evaluation(self, breaks, diagnosis):
        return policy_agent(breaks, diagnosis, self.policy, self.policy_model, self.client)


    def auto_resolutions(self, breaks, diagnosis, policy_eval):
        return auto_resolution_agent(breaks, diagnosis, policy_eval, self.resolution_model, self.client)


    def remediate(self, breaks, diagnosis, market_facts):
        return remediation_agent(breaks, diagnosis, market_facts, self.resolution_model, self.client)





market_model = "gpt-4o"
break_model = "gpt-4.1-nano"
policy_model = "gpt-4.1-nano"
resolution_model = "gpt-4.1-nano"
remediation_model = "gpt-4.1-nano"

nbim_file = "data/NBIM_Dividend_Bookings 1 (2).csv"
custody_file = "data/CUSTODY_Dividend_Bookings 1 (2).csv"

policy = POLICY_TEXT



print("")
print("----------- INITIALIZING AGENT ------------")
a = Agent(market_model, break_model, policy_model, remediation_model, remediation_model, nbim_file, custody_file, policy)





# ------------ AGENT DEVELOPMENT RUN ------------ #
# breaks = a.detect_breaks()
# with open("agent_output/market_agent_output.json", "r") as f:
#     market = json.load(f)

# with open("agent_output/break_output.json", "r") as f:
#     diagnosis = json.load(f)["diagnosis"]

# with open("agent_output/policy_output.json", "r") as f:
#     policy_eval = json.load(f)



start = time.time()

# ---------------- AGENT WORKFLOW RUN --------------- #
breaks = a.detect_breaks()
market = a.market_validation(breaks)
diagnosis = a.diagnose_breaks(breaks, market)["diagnosis"]
policy_eval = a.policy_evaluation(breaks, diagnosis)
res = a.auto_resolutions(breaks, diagnosis, policy_eval)
rem = a.remediate(breaks, diagnosis, market)


end = time.time()
print(f"Execution time: {end - start:.2f} seconds")