import os
import torch
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig
from trl import SFTTrainer, SFTConfig

# Wandb
os.environ["WANDB_PROJECT"] = "llamakandidat26"
os.environ["WANDB_ENTITY"] = "christopher-boissier-chalmers-university-of-technology"

# --- CONFIG ---
model_id = "unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit"
base_path = "/cephyr/NOBACKUP/courses/TIFX11VT2602A/filer"

output_dir = f"{base_path}/llama_coach_cp_8b"
train_path = f"{base_path}/data/processed/llm/train.jsonl"
val_path = f"{base_path}/data/processed/llm/val.jsonl"

SYSTEM_PROMPT = (
    "Du är en erfaren och försiktig löpcoach. "
    "Du ska ge tydliga, välformulerade och naturliga svar på svenska. "
    "Du ska aldrig hitta på skador eller symptom som inte nämns. "
    "Du ska alltid basera ditt svar exakt på användarens input. "
    "Du ska prioritera återhämtning och långsiktig utveckling. "
    "Du ska skriva flytande, naturligt och korrekt svenska utan konstiga formuleringar."
)

# Load model
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    device_map="auto",
    trust_remote_code=True,
)
model.config.use_cache = False

tokenizer = AutoTokenizer.from_pretrained(model_id)
tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "right"
model.config.pad_token_id = tokenizer.pad_token_id

# LoRA config
peft_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)

# Load dataset
dataset = load_dataset(
    "json",
    data_files={
        "train": train_path,
        "validation": val_path,
    }
)

def to_prompt_completion(example):
    user_parts = []
    assistant_parts = []

    for msg in example["messages"]:
        role = msg["role"].strip().lower()
        content = msg["content"].strip()

        if role == "user":
            user_parts.append(content)
        elif role == "assistant":
            assistant_parts.append(content)

    user_text = "\n".join(user_parts).strip()
    assistant_text = "\n".join(assistant_parts).strip()

    prompt = (
        f"system: {SYSTEM_PROMPT}\n"
        f"user: {user_text}\n"
        f"assistant:"
    )

    completion = f" {assistant_text}{tokenizer.eos_token}"

    return {
        "prompt": prompt,
        "completion": completion,
    }

dataset = dataset.map(to_prompt_completion)

# Keep only prompt/completion
train_cols = dataset["train"].column_names
val_cols = dataset["validation"].column_names

dataset["train"] = dataset["train"].remove_columns(
    [col for col in train_cols if col not in ["prompt", "completion"]]
)
dataset["validation"] = dataset["validation"].remove_columns(
    [col for col in val_cols if col not in ["prompt", "completion"]]
)

# Training config
training_args = SFTConfig(
    output_dir=output_dir,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=16,
    learning_rate=2e-5,
    num_train_epochs=3,
    logging_steps=1,
    optim="adamw_8bit",
    save_strategy="epoch",
    save_total_limit=1,
    fp16=True,
    report_to="wandb",
    run_name="llama31-8b-coach-v2-completion-only",
    eval_strategy="epoch",
    max_length=1024,
    packing=False,
    completion_only_loss=True,
)

trainer = SFTTrainer(
    model=model,
    args=training_args,
    train_dataset=dataset["train"],
    eval_dataset=dataset["validation"],
    peft_config=peft_config,
    processing_class=tokenizer,
)

trainer.train()

# Save adapter
trainer.model.save_pretrained(os.path.join(output_dir, "final_lora_adapter"))
print(f"Model saved in: {output_dir}")