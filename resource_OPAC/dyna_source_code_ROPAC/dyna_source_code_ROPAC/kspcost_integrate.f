      subroutine kspcost_integrate
c --
c -- This subroutine integrates the shortest path information
c -- for all the destinations into a unique array.
c --
c -  This subroutine is called from ksp_main.
c -- This subroutine does not call any other subroutines.
c --  
c -- INPUT:
c --  no specific input
c -- OUTPUT:
c --  an array contains shortest path information for all the destinations.
c --
      use muc_mod
c --
        Do 1 K=1,KPaths
         Do 2 N=1,NoOfNodes
          Do 3 IT=1,Iti_nu
          IM=BackPointr(N+1)-BackPointr(N)+1
	    if(IM.gt.MaxMove)then
		IM=MaxMove 
		! Reason 1: Only centriod will satisfy this condition:IM .gt.MaxMove  
		! Reason 2: Labels on the centriod are zero (the same) for all the movements
		! Reason 3: we do not have chances to rescan the centriod.
	    endif
! End of modification
             Do 4 M=1,IM
c	if(N.gt.206.or.IT.gt.1.or.K.gt.3.or.M.gt.12) stop
		LabelOutCost(ltype,ioccup,IDes,N,IT,K,M)=
     *          LabelCost(N,IT,K,M)
	        LabelOut(ltype,ioccup,IDes,N,IT,K,M)=
     *          Label(N,IT,K,M)
c  Points to a node,path,move,time interval respectively:
       PathPointerOut1(ltype,ioccup,IDes,N,IT,K,M)=
     *   PathPointer(N,IT,K,1,M)
       PathPointerOut2(ltype,ioccup,IDes,N,IT,K,M)=
     *   PathPointer(N,IT,K,2,M)
       PathPointerOut3(ltype,ioccup,IDes,N,IT,K,M)=
     *   PathPointer(N,IT,K,3,M)
       PathPointerOut4(ltype,ioccup,IDes,N,IT,K,M)=
     *   PathPointer(N,IT,K,4,M)
4           continue
3          continue
2         Continue
1        Continue
c --
         Do 23 N=1,NoOfNodes
c	if(N.gt.206) stop
           If(LabelCost(N,1,1,1).LT.Infinity)Then
              IM=BackPointr(N+1)-BackPointr(N)+1
	    if(IM.gt.MaxMove)then
		IM=MaxMove 
		! Reason 1: Only centriod will satisfy this condition:IM .gt.MaxMove  
		! Reason 2: Labels on the centriod are zero (the same) for all the movements
		! Reason 3: we do not have chances to rescan the centriod.
	    endif
! End of modification
             Do 33 ITime=1,Iti_nu
              Do 13 M=1,IM
               IK=Kpaths
               Know=FirstLabel(N,ITime,M)
               LabelPointerOut(ltype,ioccup,IDes,N,ITime,IK,M)=Know
               Do 30 While(IK.GT.1)
               IK=IK-1
               KTemp=Know
               Know=LabelPointer(N,ITime,KTemp,M)
	         if(know.lt.1.or.know.gt.kay)then
	            know=1
	         endif
               LabelPointerOut(ltype,ioccup,IDes,N,ITime,IK,M)=Know
30            continue
13          continue
33          continue
           endif
23      continue
c --
        return
        end
