# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.10.2
#   kernelspec:
#     display_name: Python [conda env:anaconda-florian3]
#     language: python
#     name: conda-env-anaconda-florian3-py
# ---

# %%
import os

import json
import yaml

import pandas as pd
import pyspark
from pyspark.sql import SparkSession
import pyspark.sql.types as t
import pyspark.sql.functions as f

import glow

# %%
snakefile_path = os.getcwd() + "/../Snakefile"
snakefile_path

# %%
# del snakemake

# %%
try:
    snakemake
except NameError:
    from snakemk_util import load_rule_args
    
    snakemake = load_rule_args(
        snakefile = snakefile_path,
        rule_name = 'liftover_glow',
        default_wildcards={
#             'ds_dir': 'noCAT_samplefilter_maxol20_privvar'
            'ds_dir': 'gtex_noCAT_samplefilter_maxol20_privvar'
        }
    )

# %%
print(json.dumps(snakemake.__dict__, indent=2))

# %%
import os

try:
    snakemake
except NameError:
    from snakemk_util import load_rule_args
    snakemake = load_rule_args(
        snakefile = os.getcwd() + '/../Snakefile',
        rule_name = 'liftover_glow',
        root=os.getcwd() + "/..",
    )

# %%
MEM = os.popen("ulimit -m").read()
if MEM.startswith("unlimited"):
    print("Memory not constrained, using all available memory...")
    import psutil
    MEM = psutil.virtual_memory().available / 1024
MEM = int(MEM)
N_CPU = int(os.popen("nproc").read())
print("memory: %dk" % MEM)
print("number of cores: %d" % N_CPU)

# %%
os.environ['PYSPARK_SUBMIT_ARGS'] = " ".join([
    '--driver-memory %dk' % MEM,
    'pyspark-shell'
])
os.environ['PYSPARK_SUBMIT_ARGS']
MAX_FAILURES=4
spark = (
    SparkSession.builder
    .appName('glow_liftover')
    .config("spark.jars.packages", ",".join([
        "io.projectglow:glow-spark3_2.12:1.0.0",
#         "io.delta:delta-core_2.12:0.8.0",
    ]))
#    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
#    .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
    .config("spark.local.dir", os.environ.get("TMP"))
    .config("spark.master", f"local[{N_CPU},{MAX_FAILURES}]")
    .config("spark.sql.shuffle.partitions", "2001")
#     .config("spark.sql.execution.arrow.enabled", "true")
    .config("spark.sql.execution.arrow.pyspark.enabled", "true")
#     .config("spark.sql.execution.useObjectHashAggregateExec", "false")
#     .config("spark.network.timeout", "1800s")
    .config("spark.driver.maxResultSize", "48G")
    .config("spark.default.parallelism", N_CPU / 2)
    .config("spark.files.maxPartitionBytes", 33554432)
#     .config("spark.databricks.io.cache.enabled", "true") # only enable when local storage is actually on local SSD
    .config("spark.task.maxFailures", MAX_FAILURES)
    .getOrCreate()
)
glow.register(spark)
spark

# %%
df = (
    spark
    .read
    .option("flattenInfoFields", False)
    .format('vcf')
    .load(snakemake.input['input_vcf'])
)

# %%
df = df.drop("attributes")

# %%
df.printSchema()

# %%
df = df.where(
    f.col('contigName').isin(snakemake.params['chroms'])
)

# %%
df = glow.transform("split_multiallelics", df)
df = glow.transform("normalize_variants", df, reference_genome_path=snakemake.input['reference_fasta_hg38'])

# %%
# sort by chromosome and by location
df = (
   df
   .repartitionByRange(2048, f.col("contigName"), f.col("start"))
   .sortWithinPartitions(["contigName", "start"])
   .persist()
)

# %%
OUTPUT_VCF_PQ_PATH = snakemake.output["normalized_vcf_pq"]
OUTPUT_VCF_PQ_PATH

# %%
(
    df
    .write
    .parquet(OUTPUT_VCF_PQ_PATH, mode="overwrite", partitionBy=["contigName", ])
)

# %%
df = (
    spark
    .read
    .format("parquet")
    .load(OUTPUT_VCF_PQ_PATH)
)

# %%
df.rdd.getNumPartitions()

# %%
df.printSchema()

# %%
lifted_df = glow.transform('lift_over_variants', df, chain_file=snakemake.input['chain_file'], reference_file=snakemake.input['reference_fasta'])

# %%
lifted_df.printSchema()

# %%
# lifted_df.write.format("bigvcf").save(snakemake.output['lifted_vcf'])
lifted_df.write.format("vcf").mode("overwrite").save(snakemake.output['lifted_vcf'])

# %%
