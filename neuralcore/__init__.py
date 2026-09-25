"""neuralcore — a neural knowledge system with no external memory.

Pipeline:  EXPERIENCE -> PERCEPTION -> REPRESENTATION -> NEURAL DYNAMICS -> PREDICTION -> OUTPUT

Knowledge is not stored. It is the current state of the weights and the
recurrent neural state, changed by experience itself. At inference time the
only artifact is the brain file (weights + emerging concept vectors + state).
No fact database, no vector store, no knowledge graph, no retrieval.
"""

__version__ = "0.1.0"
