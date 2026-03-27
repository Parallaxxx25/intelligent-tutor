from backend.agents.supervisor import build_tutoring_graph

def main():
    print("Building graph...")
    graph = build_tutoring_graph()
    
    print("Exporting to view_graph.png...")
    # Get the raw bytes from the built-in mermaid png renderer
    png_data = graph.get_graph().draw_mermaid_png()
    
    with open("view_graph.png", "wb") as f:
        f.write(png_data)
        
    print("Successfully saved to view_graph.png!")

if __name__ == "__main__":
    main()
