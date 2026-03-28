# Create a file named visualize_graph.py in root
from backend.agents.supervisor import build_tutoring_graph


def main():
    # Compile your graph
    graph = build_tutoring_graph()

    # Export to a PNG file using Langchain's built-in draw_mermaid_png()
    with open("tutoring_pipeline_graph.png", "wb") as f:
        f.write(graph.get_graph().draw_mermaid_png())

    print("Graph saved to tutoring_pipeline_graph.png!")


if __name__ == "__main__":
    main()
