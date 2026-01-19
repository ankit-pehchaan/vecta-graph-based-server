"""
Example usage of the Financial Life Knowledge Graph system.

This demonstrates the complete information gathering flow.
"""

from orchestrator import Orchestrator


def main():
    """Run example information gathering session."""
    # User goal
    user_goal = "I want to plan for retirement"
    
    # Initialize orchestrator
    orchestrator = Orchestrator(
        user_goal=user_goal,
        model_id="gpt-4o"
    )
    
    # Run the flow
    print("Starting information gathering session...\n")
    graph_memory = orchestrator.run()
    
    # Get summary
    summary = orchestrator.get_graph_summary()
    
    print("\n" + "="*50)
    print("SESSION SUMMARY")
    print("="*50)
    print(f"\nUser Goal: {summary['user_goal']}")
    print(f"\nNodes Collected: {len(summary['nodes_collected'])}")
    for node in summary['nodes_collected']:
        print(f"  - {node}")
    
    print(f"\nTraversal Order:")
    for i, node in enumerate(summary['traversal_order'], 1):
        print(f"  {i}. {node}")
    
    print(f"\nEdges Created: {len(summary['edges'])}")
    for edge in summary['edges']:
        print(f"  {edge['from']} → {edge['to']}: {edge['reason']}")
    
    print("\n" + "="*50)
    print("Graph data saved to memory")
    print("="*50)


if __name__ == "__main__":
    main()

