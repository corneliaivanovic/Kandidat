import torch
import json
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

base_model_id = "unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit"
adapter_path = "/cephyr/NOBACKUP/courses/TIFX11VT2602A/filer/llama_coach_cp_8b/final_lora_adapter"

SYSTEM_PROMPT = (
    "Du är en erfaren och försiktig löpcoach. "
    "Du ska ge tydliga, kortfattade svar på max 100 ord, välformulerade och naturliga svar på svenska. "
    "Du ska aldrig hitta på skador eller symptom som inte nämns. "
    "Du ska alltid basera ditt svar exakt på användarens input. "
    "Du ska prioritera återhämtning och långsiktig utveckling. "
    "Du ska skriva flytande, naturligt och korrekt svenska utan konstiga formuleringar."
)

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True,
)

tokenizer = AutoTokenizer.from_pretrained(base_model_id)
tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "left"

base_model = AutoModelForCausalLM.from_pretrained(
    base_model_id,
    quantization_config=bnb_config,
    device_map="auto",
    trust_remote_code=True,
)
base_model.config.use_cache = True
base_model.eval()

ft_base_model = AutoModelForCausalLM.from_pretrained(
    base_model_id,
    quantization_config=bnb_config,
    device_map="auto",
    trust_remote_code=True,
)
model = PeftModel.from_pretrained(ft_base_model, adapter_path)
model.config.use_cache = True
model.eval()

test_path = "/cephyr/NOBACKUP/courses/TIFX11VT2602A/filer/data/processed/llm/test.jsonl"

user_inputs = []

with open(test_path, "r", encoding="utf-8") as f:
    for line in f:
        example = json.loads(line)

        for message in example["messages"]:
            if message["role"] == "user":
                user_inputs.append(message["content"])
                break

user_inputs = [
    "Jag är 42 år och har tidigare varit elitmotionär. Just nu tränar jag 5–6 pass i veckan. Idag har jag ett tröskelpass med 3×10 minuter planerat. Jag känner mig ovanligt stel i vaderna, min vilopuls är cirka 8 slag högre än normalt och jag har haft en stressig vecka. Hur bör jag göra med dagens pass?",

    "Jag planerar att springa ett 30 km långpass mitt på dagen. Det är plötsligt 31 grader varmt och väldigt hög luftfuktighet, medan loppet jag tränar inför kommer gå i svalare temperaturer runt 10–15 grader. Hur bör jag tänka kring dagens pass?",

    "Jag är 33 år och tränar för att springa 10 km under 45 minuter, med en veckovolym på cirka 35 km. Idag har jag 4×8 minuter tröskelpass planerat. Under gårdagens pass kände jag en krampkänning i baksida lår. Hur bör jag göra idag?",

    "Jag är 17 år och tränar inför en terrängtävling, med ungefär 25 km löpning per vecka. Idag har jag backintervaller, 12×45 sekunder planerade. Redan under uppvärmningen märker jag att pulsen är cirka 15 slag högre än normalt vid samma tempo. Hur bör jag tänka kring passet?",

    "Jag är ute på ett planerat 28 km långpass i zon 2. Vid 22 km tar energin plötsligt slut, pulsen är låg men benen känns extremt tunga. Hur bör jag hantera resten av passet?",

    "Jag råkade halka med cykeln igår och skrapade upp höften ganska rejält. Inget verkar vara brutet, men det svider och stramar när jag springer och smärtan är ungefär 4 av 10. Idag har jag ett långpass på 18 km planerat. Hur bör jag göra?",

    "Jag är ute på ett planerat 8 km tröskelpass och känner mig ganska sliten mot slutet. Samtidigt ser jag att om jag fortsätter ytterligare 2 km så kan jag slå mitt personbästa på 10 km. Hur bör jag tänka i den situationen?",

    "Jag är 28 år och tränar för 10 km med en veckovolym på cirka 45 km. Idag har jag intervaller, 4×1600 meter planerade. Jag har kraftig träningsvärk i baksida lår och har svårt att sträcka ut benet ordentligt. Hur bör jag göra med passet?",

    "Jag sprang ett lopp på 10 km för två dagar sedan och känner mig fortfarande ganska dränerad i kroppen. Idag har jag ett lugnt distanspass på 6 km planerat. Hur bör jag tänka?",

    "Jag är 29 år och tränar för att springa milen under 40 minuter, med cirka 55 km per vecka. Idag har jag 5×2 km tröskelpass planerat. Jag har haft tre riktigt tuffa pass senaste veckan och benen känns stumma, men jag har ingen direkt smärta. Hur bör jag göra?",

    "Jag vaknar och känner mig lite tjock i halsen, men har ingen feber och min vilopuls är normal. Idag har jag backintervaller, 10×45 sekunder planerade. Hur bör jag tänka kring passet?",

    "Jag springer en runda som jag brukade springa för några år sedan och märker att jag är ungefär 45 sekunder per kilometer långsammare nu. Jag blir ganska nedstämd och tappar motivationen och funderar på att avbryta passet. Idag var det tänkt som ett 8 km tempopass. Hur bör jag tänka?",

    "Jag är 28 år och tränar 6 pass i veckan. Idag har jag 10 km lugn distans följt av 5×200 meter stegringar planerat. Jag har sovit bra och har normal puls, men känner mig ovanligt seg i benen utan att ha ont. Hur bör jag göra?",

    "Igår sprang jag ett lugnt pass som enligt klockan låg mycket i zon 3, trots att det kändes som zon 2. Nu är jag orolig att jag tränat för hårt. Idag har jag ett tröskelpass på 20 minuter planerat. Hur bör jag tänka?",

    "Jag är 25 år och tränar för att förbättra min 10 km-tid, med en veckovolym på cirka 28 km. Idag har jag ett lugnt distanspass på 7 km planerat. Jag har kraftig träningsvärk i framsida lår efter styrketräning. Hur bör jag göra?",

    "Jag sprang ett maraton i söndags och det är nu onsdag. Jag har fortfarande kraftig träningsvärk i benen, men känner mig sugen på att springa 10 km för att få tillbaka känslan. Hur bör jag tänka?",

    "Jag är 23 år och har nyligen satt personbästa på 5 km. Jag har sovit bra och känner mig återhämtad med låg ansträngning senaste dagarna. Hur bör jag tänka kring träningen nu?",

    "Jag har haft flera dagar med väldigt lite sömn, ungefär 4 timmar per natt i tre dagar, och min vilopuls är cirka 8 slag högre än normalt. Jag känner mig mentalt väldigt trött men vill ändå köra ett intervallpass med 8×400 meter idag. Hur bör jag göra?",

    "Jag är 25 år och en erfaren löpare som tränar cirka 65 km per vecka. Idag har jag ett 90 minuter långt pass planerat. Jag känner en lätt stelhet i baksida lår, ungefär 2 av 10 i smärta. Hur bör jag tänka?",

    "Jag är 16 år och tränar 3–4 gånger i veckan. Idag har jag ett 5 km testlopp planerat. Jag har lite smärta i armbågen som inte är relaterad till löpning, men känner mig trött och lite distraherad. Hur bör jag göra?"
]

def prompt_gen(user_input, system_prompt=SYSTEM_PROMPT):
    return (
        f"system: {system_prompt}\n"
        f"user: {user_input}\n"
        f"assistant:"
    )

def generate(model, prompt):
    inputs = tokenizer(prompt, return_tensors="pt")
    inputs = {k: v.to("cuda") for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=200,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    new_tokens = outputs[0][inputs["input_ids"].shape[1]:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

for idx, user_input in enumerate(user_inputs):
    prompt = prompt_gen(user_input)

    base_result = generate(base_model, prompt)
    ft_result = generate(model, prompt)

    print(f"\n=== CASE {idx + 1} ===")
    print("USER:")
    print(user_input)

    print("\nBASE:")
    print(base_result)

    print("\nFINETUNED:")
    print(ft_result)